import base64
import errno
from http.client import REQUEST_ENTITY_TOO_LARGE
import random
import subprocess

import requests

#api
from flask import *
import json, time

from demucs.apply import apply_model
from demucs.pretrained import get_model
from demucs.audio import AudioFile, save_audio

#fazer diretorio
import os

#send to server
import socket

#concatenate splited tracks, and overlay
import numpy as np

#split mp3
from pydub import AudioSegment

#retirar autor e nome da musica
from mutagen.mp3 import MP3

#tempo job
import time

#juntar .wav
import wave


app = Flask(__name__)
global database 
database = []

global workers
workers = []

global all_tracks
all_tracks = []

global QueueTracks
QueueTracks = []

musicProc = 0

global jobs
jobs = []

global times
times = []

start_time = 0

global Final_Tracks
Final_Tracks = []

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

#para o nome e banda da musica
def get_metadata(mp3_file):
    audio = MP3(mp3_file)
    band_name = audio["TPE1"].text[0] if "TPE1" in audio else "Unknown Band"
    music_title = audio["TIT2"].text[0] if "TIT2" in audio else "Unknown Title"
    return band_name, music_title

#sobrepor tracks
def overlay_audio(original, overlay):

    original_array = np.frombuffer(original, dtype=np.int16)
    overlay_array = np.frombuffer(overlay, dtype=np.int16)

    max_length = max(len(original_array), len(overlay_array))
    original_array = np.pad(original_array, (0, max_length - len(original_array)), mode='constant')
    overlay_array = np.pad(overlay_array, (0, max_length - len(overlay_array)), mode='constant')

    mixed_array = np.add(original_array, overlay_array)


    mixed_array = np.clip(mixed_array, -32768, 32767)

    mixed_data = mixed_array.astype(np.int16).tobytes()

    return mixed_data

@app.route('/', methods=['GET'])
def home():    
    
    print(ip_address)
    json_data = json.dumps(database)
    return render_template('home.html', data=json_data)

@app.route('/music', methods=['GET', 'POST']) 
def list_music():

    if request.method == 'GET':
        data_set = database
        return json.dumps(data_set)
    else:
        #initialize musica
        f = request.files['file']
        f.save(f.filename)  

        music_id = random.randint(1, 100000000)

        if f.filename  in [i['file'] for i in database]:
            
            dic_music = {'message': 'Musica já foi postada', 'file': f.filename}
            return json.dumps(dic_music)
        
        else:
            
            band, music_name = get_metadata(f.filename)
        
            tracks_array = [{"name": "bass", "track_id" : 1}, {"name": "drums", "track_id" : 2}, {"name": "other", "track_id" : 3}, {"name": "vocals", "track_id" : 4} ]
            tracks_dic = {'bass': 0, 'drums': 0, 'other': 0, 'vocals': 0}

            dic_music = {'music_id': music_id, 'name': music_name, 'band':band, 'tracks' : tracks_array ,'file': f.filename, 'processed': 0, 'tracks_to_proc': tracks_dic}
            database.append(dic_music)
            return json.dumps(dic_music)
            

@app.route('/music/', methods=['GET', 'POST'])
def processar_musicid(): 
    global musicProc  
    global times
    global start_time

    if request.method == 'GET':

        music_id = int(request.args.get('music_id'))
        print(music_id)
        musica = {}
        
        for i in database:
            if int(i['music_id']) == music_id:    
                musica = i
        
        #musica já processada
        if musica['processed'] == 1:
            
            inst = []

            count_tracks = 0
            for m in musica['tracks_to_proc']:
                if musica['tracks_to_proc'][m] == 1:
                    count_tracks += 1
                    inst.append({"name" : m, "track" : "http://" + ip_address + ":7777/download/" + str(musica['music_id']) + "/" + m })

            dic = {"progress": 0, "instruments" : inst, "final": "http://" + ip_address + ":7777/download/" + str(musica['music_id']) + "/mixed"}
            
            return json.dumps(dic), 200

        else:
        #retirar o tempo estimado
            sumBits = 0
            sumTime = 0

            with open('track_stats.txt', 'r') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        bits, tim = line.split(' ')
                        sumBits += int(bits)
                        sumTime += float(tim)

            tamanho_tot = 0
            for q in QueueTracks:
                tamanho_tot += q['size']
                if q['music_id'] == musica['music_id']:
                    break
            
            time_music = (tamanho_tot * sumTime) / sumBits
            print(time_music)
            processed_time = time.time() - start_time

            estimado = time_music - processed_time
            if estimado < 0:
                estimado = 0

            dic = {"progress": estimado}

            return json.dumps(dic), 200

    else:
        #POST 
        post_dic = json.loads(request.data)
        print(post_dic)
        post_dic['music_id'] = int(post_dic['music_id'])

        for music in database:
            if int(music['music_id']) == int(post_dic['music_id']):
                database.remove(music)

        #adicionar a musica com os instrumentos certos
        database.append(post_dic)

        print(post_dic['processed'])
        if post_dic['processed'] != 0:
            return json.dumps({'message': "Música já foi processada"}) 
        
        with open(post_dic['file'], 'rb') as f:
            data = f.read()

        queue_track = post_dic
        queue_track['size'] = len(data)
        #adicionar musica à queue
        if (queue_track not in QueueTracks):       
            QueueTracks.append(queue_track)

        #se uma musica estiver a processar a função termina
        if musicProc == 1:
            print("Espera")
            return json.dumps({'message': "Na Queue"}) 
                
        print(int(post_dic['music_id']))
        musicProc = 1
        times = []
        start_time = time.time()

        part_size = len(data) // len(workers)
        print(part_size)

        #guardar partes
        parts = []
        # dividir musica
        for w in range(len(workers)):
            start = w * part_size
            end = (w + 1) * part_size
            part = data[start:end]
            parts.append(part)

        #enviar para os workers              
        iter = 0
        for job in workers:
                    
            times.append({int(job['job_port']) : start_time })
            socketApi = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            socketApi.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            socketApi.connect((job['id'], int(job['job_port'])))
            socketApi.setblocking(0)
            
            time.sleep(1)
            socketApi.send(len(json.dumps(post_dic)).to_bytes(4, byteorder='big'))
            socketApi.send(json.dumps(post_dic).encode('utf-8'))
            print(iter, "enviar para Worker")
            socketApi.send(len(parts[iter]).to_bytes(4, byteorder='big'))
                    
            dataPart = parts[iter]
            buffer_size = 65536
            sent_total = 0
                    
            while True:
                data_part = dataPart[sent_total:sent_total + buffer_size]
                if not data_part:
                    break

                while sent_total < len(dataPart):
                    try:
                        if not dataPart[sent_total:sent_total + buffer_size]:
                            break
                        sent = socketApi.send(dataPart[sent_total:sent_total + buffer_size])
                        print(sent_total)
                        sent_total += sent
                    except socket.error as e:
                        if e.errno == errno.EAGAIN or e.errno == errno.EWOULDBLOCK:
                            time.sleep(0.1)
                            continue
                        else:
                            print(e)
                            break
                   
            socketApi.close()

            tracks_Array = []
            for instr in post_dic['tracks_to_proc']:
                if post_dic['tracks_to_proc'][instr] == 1:
                    if instr == 'bass':
                        tracks_Array.append(1)
                    elif instr == 'drums':
                        tracks_Array.append(2)
                    elif instr == 'other':
                        tracks_Array.append(3)
                    elif instr == 'vocals':
                        tracks_Array.append(4)
                    else:
                        continue

            #inicializar job 
            dic = {'job_id': int(str(post_dic['music_id']) + "" + str(iter + 1)) , 'size' : len(parts[iter]), 'time' : 0, 'music_id' : post_dic['music_id'], 'track_id' : tracks_Array }
            if (dic not in jobs):
                jobs.append(dic)
                
            iter += 1

        return json.dumps({'message': 'Music added successfully.'}), 200
          
@app.route('/workers', methods=['GET', 'POST'])
def worker():
    global workers
    
    if request.method == 'POST':
        worker_data = json.loads(request.data)
        print(worker_data)

        #se um worker já existir e for postado novamente é para ser removido
        for worker in workers:
            if worker['job_port'] == worker_data['job_port']:
                print("tou aqui")
                workers.remove(worker)
                return json.dumps({'message': 'Worker removed'}), 200

        
        workers.append(worker_data)
        return json.dumps({'message': 'Worker disponível'}), 200
    
    else:
        print(workers)
        return json.dumps(workers)
    
@app.route('/success/', methods = ['GET'])  
def success():  
    
    music_id = int(request.args.get('music_id'))
    print(music_id)
    musica = {}
       
    for i in database:
        if int(i['music_id']) == music_id:    
            musica = i

    if musica['processed'] != 0:
        return json.dumps({'message': "Música já foi processada"}) 

    if musicProc == 1:
        print("Espera")
        return json.dumps({'message': "Na Queue"}) 

    return render_template('Acknowledgement.html', data=musica)
    
@app.route('/reset', methods=['POST'])
def reset_data():
    global database
    global workers
    global jobs
    global QueueTracks
    global times
    global Final_Tracks
    global start_time 
    global musicProc
    global all_tracks

    #enviar mensagem de erro para os Workers ->  {'music_id': 0}
    for job in workers:
                    
        socketApi = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        socketApi.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        socketApi.connect((job['id'], int(job['job_port'])))

        post_dic = {'music_id': 0}
        socketApi.send(len(json.dumps(post_dic)).to_bytes(4, byteorder='big'))
        socketApi.send(json.dumps(post_dic).encode('utf-8'))

        socketApi.close()

    #inicializar todas as variaveis
    database = []
    workers = []
    jobs = []
    QueueTracks = []
    times = []
    Final_Tracks = []
    start_time = 0
    musicProc = 0
    all_tracks = []
    
    return render_template('home.html', data=json.dumps(database))

@app.route('/recv_split', methods=['POST'])
def recv_split():
    global musicProc   
    global all_tracks
    global times
    global Final_Tracks
    
    tracks = json.loads(request.data)
    all_tracks.append(tracks)

    end_time = time.time()  # Stop measuring time
    print(int(tracks['port']))
    
    #tempo de cada worker
    for dic in times:
        for key in dic:
            if key == int(tracks['port']):
                print(dic[key])

                processing_time = end_time - dic[key]
        
                print("Processing time:", processing_time)
                dic[key] = processing_time
   
    #ix é a variavel que identifica qual a part que o Worker processou
    ix = 1
    for w in workers:
        if w['job_port'] == int(tracks['port']):
            break
        ix += 1

    id_job = int(str(tracks['music_id']) + str(ix))

    print("ids -->",id_job)
    print(times)

    #atualizar o job
    for job in jobs:
        if job['job_id'] == id_job:
            job['time'] = times[ix - 1][tracks['port']]

    #so entra se estivarem todos os Workers acabado de processar
    if len(all_tracks) == len(workers):
       
        print(len(all_tracks),"aqui")
        print(len(workers))
        worker_ports = [worker['job_port'] for worker in workers]
        all_track_ports = [track['port'] for track in all_tracks]

        #verifica se os Workers entraram na ordem certa, se não ordena
        if worker_ports != all_track_ports:
            print("desordenado")
            sorted_tracks = sorted(all_tracks, key=lambda track: worker_ports.index(track['port']))
            all_tracks[:] = sorted_tracks

        with open("track_stats.txt", "r") as f:
            lines = f.read().splitlines()  

        for jb in jobs:
            line = str(jb['size']) + " " + str(jb['time'])
            #verifica elementos repetidos
            if line not in lines:
                #atualizar estatisticas
                with open("track_stats.txt", "a") as f:
                    f.write(line + "\n")
   
        directory = f"tracks_{all_tracks[0]['music_id']}"
        parent = os.path.dirname(directory)
        path = os.path.join(parent, directory)
        if not os.path.exists(path):
            print("dir")
            os.mkdir(path)

        bass_data = b''
        drums_data = b''
        other_data = b''
        vocals_data = b''
        mixed_data = np.zeros((0,), dtype=np.int16)
       
        #juntar partes
        for m_track in all_tracks:
            if m_track['bass'] != 0:
                bass_data += base64.b64decode(m_track['bass'])

            if m_track['drums'] != 0:
                drums_data += base64.b64decode(m_track['drums'])
            
            if m_track['other'] != 0:
                other_data += base64.b64decode(m_track['other'])
            
            if m_track['vocals'] != 0:
                vocals_data += base64.b64decode(m_track['vocals'])
          

        sample_width = 2
        sample_rate = 44100  
        num_channels = 2  

        #guarda a data bin de cada track
        final_tracks_data = {}
        
        if tracks['bass'] != 0:
            final_tracks_data['bass'] = bass_data
            
            mixed_data = overlay_audio(mixed_data, bass_data)
            with wave.open(f"{path}/bass.wav", 'wb') as wav_file:
                wav_file.setsampwidth(sample_width)
                wav_file.setframerate(sample_rate)
                wav_file.setnchannels(num_channels)
                wav_file.writeframes(bass_data)

        if tracks['drums'] != 0:
            final_tracks_data['drums'] = drums_data

            mixed_data = overlay_audio(mixed_data, drums_data)
            with wave.open(f"{path}/drums.wav", 'wb') as wav_file:
                wav_file.setsampwidth(sample_width)
                wav_file.setframerate(sample_rate)
                wav_file.setnchannels(num_channels)
                wav_file.writeframes(drums_data)

        if tracks['other'] != 0:
            final_tracks_data['other'] = other_data

            mixed_data = overlay_audio(mixed_data, other_data)
            with wave.open(f"{path}/other.wav", 'wb') as wav_file:
                wav_file.setsampwidth(sample_width)
                wav_file.setframerate(sample_rate)
                wav_file.setnchannels(num_channels)
                wav_file.writeframes(other_data)
                    
        if tracks['vocals'] != 0:
            final_tracks_data['vocals'] = vocals_data

            mixed_data = overlay_audio(mixed_data, vocals_data)
            with wave.open(f"{path}/vocals.wav", 'wb') as wav_file:
                final_tracks_data['vocals']

                wav_file.setsampwidth(sample_width)
                wav_file.setframerate(sample_rate)
                wav_file.setnchannels(num_channels)
                wav_file.writeframes(vocals_data)

        final_tracks_data['mixed'] = mixed_data
        final_tracks_data['music_id'] = tracks['music_id']
        Final_Tracks.append(final_tracks_data)

        with wave.open(f"{path}/mixed.wav", 'wb') as wav_file:
            wav_file.setsampwidth(sample_width)
            wav_file.setframerate(sample_rate)
            wav_file.setnchannels(num_channels)
            wav_file.writeframes(mixed_data)

        for music in database:
            if int(music['music_id']) == int(tracks['music_id']):
                music['processed'] = 1

        #nenhuma música a ser processada
        musicProc = 0
        print(musicProc)

        #tirar que foi processado da queue
        QueueTracks.remove(QueueTracks[0])
        print(QueueTracks)
        if len(QueueTracks) > 0:
            #processar musica que estava à espera à mais tempo
            requests.post('http://'+ str(ip_address) +':7777/music/', json.dumps(QueueTracks[0]))

        all_tracks = []

    return json.dumps({'message': 'Split concluido'}), 200

@app.route('/jobs', methods=['GET']) 
def list_jobs():
    data_set = []

    for job in jobs:
        data_set.append(job['job_id'])

    return json.dumps(data_set)

@app.route('/jobs/', methods=['GET']) 
def get_job():
    job_id = int(request.args.get('job_id'))
    job = {}

    for j in jobs:
        if j['job_id'] == job_id:
            job = j

    return json.dumps(job)

@app.route('/download/<int:music_id>/<instrumento>', methods=['GET'])
def download(music_id, instrumento):
    global Final_Tracks

    print("a") 
    for f_track in Final_Tracks:

        if int(f_track['music_id']) == int(music_id):
            sample_width = 2
            sample_rate = 44100  
            num_channels = 2  

            with wave.open('data.wav', 'wb') as wav_file:
                wav_file.setsampwidth(sample_width)
                wav_file.setframerate(sample_rate)
                wav_file.setnchannels(num_channels)
                wav_file.writeframes(f_track[instrumento])


            # Send the .wav file as a download
            with open('data.wav', 'rb') as file:
                data = file.read()

            os.remove(f"{os.getcwd()}/data.wav")

            return Response(data, mimetype="audio/wav", headers={"Content-Disposition": "attachment;filename= "+ instrumento + "_" + str(music_id) + ".wav"})



    return json.dumps(music_id)

@app.route('/try_again', methods=['POST'])
def tryagain():
    #se o split falhar 5 vezes a musica vai ser mandada novamente
    global musicProc

    failed_track = json.loads(request.data)

    musica = {}
    for m in database:
        if m['music_id'] == failed_track['music_id']:
            musica = m

    with open(musica['file'], 'rb') as f:
            data = f.read()

    part_size = len(data) // len(workers)
    print(part_size)

    #guardar partes
    parts = []
    # parts.append(data)
    for w in range(len(workers)):
        start = w * part_size
        end = (w + 1) * part_size
        part = data[start:end]
        parts.append(part)

               
    iter = 0
    for w in workers:
        if w["job_port"] == failed_track['job_port']:
            break
        iter += 1

    if {failed_track['job_port'] : start_time } not in times:
        times.append({failed_track['job_port'] : start_time })

    socketApi = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    socketApi.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    socketApi.connect((failed_track['id'], failed_track['job_port']))
    socketApi.setblocking(0)
                 
    socketApi.send(len(json.dumps(musica)).to_bytes(4, byteorder='big'))
    socketApi.send(json.dumps(musica).encode('utf-8'))
    print(iter, "enviar para o Worker")
    socketApi.send(len(parts[iter]).to_bytes(4, byteorder='big'))
    
    dataPart = parts[iter]
    buffer_size = 65536
    sent_total = 0
                   
    while True:
        data_part = dataPart[sent_total:sent_total + buffer_size]
        if not data_part:
            break

        while sent_total < len(dataPart):
            try:
                if not dataPart[sent_total:sent_total + buffer_size]:
                    break
                sent = socketApi.send(dataPart[sent_total:sent_total + buffer_size])
                print(sent_total)
                sent_total += sent
            except socket.error as e:
                if e.errno == errno.EAGAIN or e.errno == errno.EWOULDBLOCK:
                    time.sleep(0.1)
                    continue
                else:
                    print(e)
                    break
                   
    socketApi.close()

    tracks_Array = []
    for instr in musica['tracks_to_proc']:
        if musica['tracks_to_proc'][instr] == 1:
            if instr == 'bass':
                tracks_Array.append(1)
            elif instr == 'drums':
                tracks_Array.append(2)
            elif instr == 'other':
                tracks_Array.append(3)
            elif instr == 'vocals':
                tracks_Array.append(4)
            else:
                continue

    #job init
    dic = {'job_id': int(str(musica['music_id']) + "" + str(iter + 1)) , 'size' : len(parts[iter]), 'time' : 0, 'music_id' : musica['music_id'], 'track_id' : tracks_Array }
    if (dic not in jobs):
        jobs.append(dic)

    return json.dumps({'message':'Trying again'})

if __name__ == '__main__':
    app.run(host="0.0.0.0",port=7777, debug=True)
