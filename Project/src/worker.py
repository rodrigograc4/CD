import base64
import errno
import fcntl

import os
import selectors
import shutil
import sys
import socket
import json
import random
import time
import requests

#split tracks
import argparse
from demucs.apply import apply_model
from demucs.pretrained import get_model
from demucs.audio import AudioFile, save_audio

#turn into mp3
from pydub import AudioSegment
from io import BytesIO

#reset
import threading
import signal


#retirar ip
def get_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip_address = s.getsockname()[0]
        s.close()
        return ip_address
    except socket.error:
        return None
    
ip_address = get_ip()

def split(args, dic):
    # get the model
    model = get_model(name='htdemucs')
    model.cpu()
    model.eval()

    # load the audio file
    wav = AudioFile(args.i).read(streams=0,
    samplerate=model.samplerate, channels=model.audio_channels)
    ref = wav.mean(0)
    wav = (wav - ref.mean()) / ref.std()
    
    # apply the model
    sources = apply_model(model, wav[None], device='cpu', progress=True, num_workers=1)[0]
    sources = sources * ref.std() + ref.mean()

    # store the model
    for source, name in zip(sources, model.sources):
        if dic['tracks_to_proc'][name] == 1:
            stem = f'{args.o}/{name}.wav'
            save_audio(source, str(stem), samplerate=model.samplerate)

class Worker:

    def __init__(self):
        """Initializes chat server."""
        if (len(sys.argv) == 2):
            self.api_id = sys.argv[1]
        else:
            self.api_id = '127.0.0.1'

        self.host = ip_address
        self.port = random.randint(5000,9999)

        #verifica se a porta está a ser usada
        jobs = requests.get('http://'+ self.api_id +':7777/workers')
        self.job_data = json.loads(jobs.content)
        bol = True
        while True:
            for job in self.job_data:
                if job['job_port'] == self.port:
                    self.port = random.randint(5000,9999)
                    bol = False
                    break
               
            if bol:
                break

        
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) 
        self.socket.bind((self.host, self.port))
        self.socket.listen(100)
        
        self.sel = selectors.DefaultSelector()
        self.sel.register(self.socket, selectors.EVENT_READ, self.accept_client)

        #register worker
        print(sys.argv)
        data_port = {'job_port': self.port, 'id' : self.host}
        self.r = requests.post('http://'+ self.api_id +':7777/workers', data=json.dumps(data_port))

        self.api_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        #threads para o reset enquanto o split está a ser feito
        self.count_error = 0
        self.reset = False
        self.lock = threading.Lock()
        self.stop_event = threading.Event()

        self.socket_thread = threading.Thread(target=self.Thread_loop)
        self.socket_thread.start()

        self.split = False

    def accept_client(self, sock, mask ):
        """Accepts new connection."""
        (conn, addr) = sock.accept()  
      

        self.sel.register(conn, selectors.EVENT_READ, self.read)

        if self.split == True:
            self.reset = True
        else:
            self.reset = False

        print(self.reset)
        print('accepted', conn, 'from', addr)


    def read(self, conn, mask):
        """Reads data from connection."""


        print("reading")
        
        self.api_sock = conn

        len_data = int.from_bytes(conn.recv(4), byteorder='big')
        print(len_data)

        data = conn.recv(len_data)

        if data:
            print("entrou")
            dic = json.loads(data.decode('utf-8', errors='ignore'))

            #id de erro = 0
            if dic['music_id'] == 0:
                print(dic)
                if os.path.exists(f"{os.getcwd()}/track_not_split_{self.port}.mp3"):
                    os.remove(f"{os.getcwd()}/track_not_split_{self.port}.mp3")

                if os.path.exists(f"{os.getcwd()}/tracks_{self.port}"):
                    shutil.rmtree(f"{os.getcwd()}/tracks_{self.port}")
              
                os.kill(os.getpid(), signal.SIGTERM)
                
            print(dic)
        else:
            dic = {"music_id": 0}


        file_size = int.from_bytes(conn.recv(4), byteorder='big')
        print(file_size, "tamanho enviado 1")
        
        #receber data da musica
        data_bin = b''
        bytes_received = 0
        while bytes_received < file_size:
            print("recebendo")
            try:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                data_bin += chunk
                print(bytes_received)
                bytes_received += len(chunk)
            except socket.error as e:
                if e.errno == errno.EAGAIN or e.errno == errno.EWOULDBLOCK:
                    time.sleep(0.1)
                    continue
                else:
                    print(e)
                    break
        conn.close()
        self.sel.unregister(conn)
        

        print(bytes_received, "enviados codificado 2")  
        print(dic)
        audio_segment = AudioSegment.from_file(BytesIO(data_bin), format="mp3")
        audio_segment.export(f"track_not_split_{self.port}.mp3", format="mp3")

        directory = f"tracks_{self.port}"
        parent = os.path.dirname(directory)
        path = os.path.join(parent, directory) 
        if not os.path.exists(path):
            print("novo")
            os.mkdir(path)

        self.reset = True
        self.stop_event.set()
        # socket_thread = threading.Thread(target=self.Thread_loop)
        

        #começar a tentar splitar
        fail = self.trySplit(dic)

        print(fail)
        if fail == None:
            if os.path.exists(f"{os.getcwd()}/track_not_split_{self.port}.mp3"):
                os.remove(f"{os.getcwd()}/track_not_split_{self.port}.mp3")

            if os.path.exists(f"{os.getcwd()}/tracks_{self.port}"):
                shutil.rmtree(f"{os.getcwd()}/tracks_{self.port}")

            return
    
        os.remove(f"{os.getcwd()}/track_not_split_{self.port}.mp3")

        #get bass
        if int(dic['tracks_to_proc']["bass"]) == 1:
            with open(f"tracks_{self.port}/bass.wav", 'rb') as f:
                bass = base64.b64encode(f.read()).decode('utf-8')
        else:
            bass = 0

        #get drums
        if int(dic['tracks_to_proc']['drums']) == 1:
            with open(f"tracks_{self.port}/drums.wav", 'rb') as f:
                drums = base64.b64encode(f.read()).decode('utf-8')
        else:
            drums = 0

        #get other
        if int(dic['tracks_to_proc']['other']) == 1:
            with open(f"tracks_{self.port}/other.wav", 'rb') as f:
                other = base64.b64encode(f.read()).decode('utf-8')
        else:
            other = 0

        #get vocals
        if int(dic['tracks_to_proc']['vocals']) == 1:
            with open(f"tracks_{self.port}/vocals.wav", 'rb') as f:
                vocals = base64.b64encode(f.read()).decode('utf-8')
        else:
            vocals = 0

        #elimnar pasta criada
        shutil.rmtree(f"{os.getcwd()}/tracks_{self.port}")

        #post data to api 
        tracks = {"port": self.port, "music_id": str(dic['music_id']) ,"bass": bass, "drums":drums, "other":other ,"vocals":vocals}
        print("recv")
        requests.post('http://'+ self.api_id + ':7777/recv_split', data=json.dumps(tracks))

    def trySplit(self, dic):

        try:
            #split track
            parser = argparse.ArgumentParser(description='Split an audio track', formatter_class=argparse.ArgumentDefaultsHelpFormatter)
            parser.add_argument('-i', type=str, help='input mp3', default=f"track_not_split_{self.port}.mp3")
            parser.add_argument('-o', type=str, help='output folder', default=f"tracks_{self.port}")
            args, _ = parser.parse_known_args()
            
            self.split = True
            split(args, dic)
            self.split = False
            self.reset = False
            self.stop_event.clear()
            return 1
            #split track

        except:
            self.count_error += 1
                
            if self.count_error == 5:
                self.reset = False
                self.stop_event.clear()
                self.count_error = 0
                
                all_workers =  requests.get('http://' + self.api_id + ':7777/workers')
                all_workers = json.loads(all_workers.text)

                error_data = {"music_id": dic['music_id'], 'job_port' : self.port, 'id' : ip_address}
                 
                requests.post('http://'+ self.api_id +':7777/try_again', data = json.dumps(error_data))

                return 0
            else:
                print("erro ao splitar, nr:",self.count_error)
                self.reset = True
                self.stop_event.set()
                self.trySplit(dic)

    def loop(self):
        """Loop indefinetely."""
        while True:
            try: 
                events = self.sel.select()
                for key, mask in events:
                    callback = key.data
                    callback(key.fileobj, mask)
            except KeyboardInterrupt:
                print("KeyboardInterrupts")

                all_workers =  requests.get('http://' + self.api_id + ':7777/workers')
                all_workers = json.loads(all_workers.text)
                error_data = {"job_port": self.port, 'id' : ip_address}
        
                if error_data in all_workers:
                    requests.post('http://' + self.api_id + ':7777/workers', data=json.dumps(error_data))
                sys.exit()
                
    def Thread_loop(self):
        try:
            while True:
                if self.reset:
                    self.stop_event.wait()  # Wait until the event is set
                    
                    if not self.stop_event.is_set():  # Double-check the event state
                        continue
                    events = self.sel.select()
                    for key, mask in events:
                        callback = key.data
                        callback(key.fileobj, mask)
                else:
                    continue

        except Exception as e:
            print("Exception in thread Thread-1:", e)