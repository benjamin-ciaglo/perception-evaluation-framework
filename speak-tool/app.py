# app.py
# flask app

# flask libraries
from flask import Flask, request, render_template, redirect, session, send_from_directory, Response, abort
# python/third-party libraries
import os
import urllib
import time
import werkzeug
import geoip2.database
import boto3
import re
import pickle
import uuid
# helpers
import scripts
from ast import literal_eval
import sys

# Add the 'perception-evaluation-framework' directory to the Python search path
framework_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(framework_path)

# Import the 'experiment' module from 'world'
from world import experiment

# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# setup
# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
env = 'production' # 'production' vs. 'sandbox'

with open("app_config.txt", "r+") as config:
	for line in config:
		exec(line)

localtime = time.asctime(time.localtime(time.time()))
print("\n\n----- NEW SESSION %s, ENVIRONMENT: %s ---------------------------" % (localtime, env))

app = Flask(__name__)
app.config.update(SESSION_COOKIE_SAMESITE="None", SESSION_COOKIE_SECURE=True)
app_dir = os.path.abspath(os.path.dirname(__file__))					# global directory var to make code more readable
app.secret_key = 'SooperDooperSecret'							# secret key used for session cookies
iplocator = geoip2.database.Reader(app_dir+'/scripts/geolite2/GeoLite2-City.mmdb')	# ip address location lookup
#sslify = SSLify(app)									# force SSL (to comply with MTurk)

# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# test
# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
@app.route('/')
def hello_world():
	return str("Hello world!")

@app.route('/<audio_file_name>')
def returnAudioFile(audio_file_name):
    if not audio_file_name.endswith('.wav'):
        return abort(401)
    directory = werkzeug.security.safe_join(save_location, env)
    path = audio_file_name
    return send_from_directory(directory, path)

@app.errorhandler(401)
def custom_401(error):
    return Response('You have already started to attempt this task, and it can only be assigned once per worker. Please resume the assignment you started from "Your HITs Queue". Please contact an administrator if you believe you should not be receiving this message.', 401, {})

def pop_sqs_item():
    sqs = boto3.client('sqs', region_name='us-east-1')
    queue_url = 'https://sqs.us-east-1.amazonaws.com/180367849334/percept_eval_deployment_queue'
    response = sqs.receive_message(
        QueueUrl=queue_url,
        AttributeNames=[
            'All'
        ],
        MaxNumberOfMessages=1,
    )
    if 'Messages' in response:
        message = response['Messages'][0]
        receipt_handle = message['ReceiptHandle']
        sqs.delete_message(
            QueueUrl=queue_url,
            ReceiptHandle=receipt_handle
        )
        print('Received and deleted message: %s' % message)
    else:
        print('No messages in queue.')
    return message

# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# STEP 0: initialize test
# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
@app.route('/<proctor_name>/<battery_name>/<perceptual_trait>')
def init_test(proctor_name, battery_name, perceptual_trait):
	if proctor_name == 'turk':
		ass_id, hit_id, submit_path, worker_id, arg_string = scripts.get_args()

		if (worker_id is not None):
			trait_config_filename = os.path.join(save_location,env,worker_id+"_"+ass_id+"_trait_config.txt")
			with open(trait_config_filename, 'w') as trait_handle:
				trait_handle.write(perceptual_trait)
			worker_already_started_this_task = os.path.exists(os.path.join(save_location, env, worker_id + ".txt"))
			worker_resuming_task = False
			if worker_already_started_this_task:
				with open(os.path.join(save_location, env, worker_id + ".txt"), 'r') as rf:
					line = rf.readline().strip('\n').split('_')
					prev_ass_id, prev_hit_id = line[0], line[1]
					worker_resuming_task = ass_id == prev_ass_id and hit_id == prev_hit_id
			if worker_already_started_this_task and not worker_resuming_task:
				return abort(401)
			else:
				nextPage = '/consent/' + proctor_name + '/' + battery_name + '/' + '0' + arg_string
				print('init: ')
				print('ass_id: ', ass_id, ' hit_id: ', hit_id, ' submit_path: ', ' worker_id: ', worker_id)
				print('submit_path: ', submit_path, ' arg_string: ', arg_string)
				session.clear()
				session[ass_id + "_starttime"] = time.time() # start task timer
		else:
			nextPage = '/consent/' + proctor_name + '/' + battery_name + '/' + '0' + arg_string
		return redirect(nextPage)
	elif proctor_name == 'appen':
		ass_id, worker_id = str(uuid.uuid4()), str(uuid.uuid4())
		trait_config_filename = os.path.join(save_location,env,worker_id+"_"+ass_id+"_trait_config.txt")
		with open(trait_config_filename, 'w') as trait_handle:
			trait_handle.write(perceptual_trait)
		arg_string = '?assignmentId=' + ass_id + '&workerId=' + worker_id
		nextPage = '/consent/' + proctor_name + '/' + battery_name + '/' + '0' + arg_string
		print('init: ')
		print('ass_id: ', ass_id, ' worker_id: ', worker_id)
		session.clear()
		session[ass_id + "_starttime"] = time.time() # start task timer
		pickle_file_path = os.path.join(save_location, env, worker_id + "_" + ass_id + "_starttime" ".pickle")
		with open(pickle_file_path, "wb") as file:
			pickle.dump(time.time(), file)
		return redirect(nextPage)
	else:
		return abort(404)

# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# STEP 0b: show recruitment/consent info, give test
# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
@app.route('/consent/<proctor_name>/<battery_name>/<test_idx>')
def consent(proctor_name, battery_name, test_idx):
	if proctor_name == 'turk':
		ass_id, hit_id, submit_path, worker_id, arg_string = scripts.get_args()

		print('consent: ')
		print('ass_id: ', ass_id, ' hit_id: ', hit_id, ' submit_path: ', ' worker_id: ', worker_id)
		# redirect worker to first question within HIT, multiple_attempts_true = 0 (false)
		if worker_id is not None:
			nextPage = '/' + proctor_name + '/' + battery_name + '/record-voice/' + test_idx + '/0/0' + arg_string
			return render_template(recruitment_and_consent_template,
					nextPage=nextPage
				)
		else:
			nextPage = '/consent/' + proctor_name + '/' + battery_name + '/' + test_idx + arg_string
			return render_template(recruitment_and_consent_template,
					nextPage=nextPage
				)
	elif proctor_name == 'appen':
		ass_id, worker_id, arg_string = scripts.get_args('appen')

		print('consent: ')
		print('ass_id: ', ass_id, ' worker_id: ', worker_id)
		# redirect worker to first question within HIT, multiple_attempts_true = 0 (false)
		if worker_id is not None:
			nextPage = '/' + proctor_name + '/' + battery_name + '/record-voice/' + test_idx + '/0/0' + arg_string
			return render_template(recruitment_and_consent_template,
					nextPage=nextPage
				)
		else:
			nextPage = '/consent/' + proctor_name + '/' + battery_name + '/' + test_idx + arg_string
			return render_template(recruitment_and_consent_template,
					nextPage=nextPage
				)
	else:
		return abort(404)

# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# STEP 1: record user input
# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
@app.route('/<proctor_name>/<battery_name>/record-voice/<test_idx>/<question_idx>/<multiple_attempts_true>')
def record(proctor_name, battery_name, test_idx, question_idx, multiple_attempts_true):
	if proctor_name == 'turk':
		ass_id, hit_id, submit_path, worker_id, arg_string = scripts.get_args()

		print('record: ')
		print('ass_id: ', ass_id, ' hit_id: ', hit_id, ' submit_path: ', ' worker_id: ', worker_id)
		worker_already_started_this_task = os.path.exists(os.path.join(save_location, env, worker_id + ".txt"))
		if not worker_already_started_this_task:
			with open(os.path.join(save_location, env, worker_id + ".txt"), 'w') as wf:
				wf.write(ass_id + '_' + hit_id)
			message = pop_sqs_item()
			entrainment_features = message['Body']
			entrainment_config_filename = os.path.join(save_location,env,worker_id+"_"+ass_id+"_entrainment_config.txt")
			with open(entrainment_config_filename, 'w') as entrainment_handle:
				entrainment_handle.write(entrainment_features)
		if (multiple_attempts_true == '1'):
			print('\n  ---- worker recording (failed the first time) -----')
		else:
			print('\n  ---- worker recording for', battery_name, '(new) -----')
		scripts.print_row('assignmentId:', ass_id)
		scripts.print_row('workerId:', worker_id)
		scripts.print_row('test:', test_idx)
		scripts.print_row('question:', question_idx)

		is_preview = (ass_id is None)
		
		if (not is_preview) and (ass_id + "_starttime" in session):
			is_not_preview = not is_preview
			return render_template(record_template,
				error=multiple_attempts_true,
				proctor=proctor_name,
				battery=battery_name,
				test=test_idx,
				question=question_idx,
				questionIdx1Based=str(int(question_idx)+1),
				numQuestions=n,
				assignmentId=ass_id,
				hitId=hit_id,
				turkSubmitTo=submit_path,
				workerId=worker_id,
			is_not_preview=is_not_preview)
		else:
			print(session)
			print(ass_id)
			return render_template('base/cookie_error.html',
				assignmentId=ass_id,
				hitId=hit_id,
				workerId=worker_id,
				turkSubmitTo=submit_path,
				retrySubmitUrl="/{}/{}/record-voice/{}/{}/{}".format(proctor_name, battery_name,
								test_idx, question_idx, multiple_attempts_true))
	elif proctor_name == 'appen':
		ass_id, worker_id, arg_string = scripts.get_args('appen')

		with open(os.path.join(save_location, env, worker_id + ".txt"), 'w') as wf:
			wf.write(ass_id)
		message = pop_sqs_item()
		entrainment_features = message['Body']
		entrainment_config_filename = os.path.join(save_location,env,worker_id+"_"+ass_id+"_entrainment_config.txt")
		with open(entrainment_config_filename, 'w') as entrainment_handle:
			entrainment_handle.write(entrainment_features)

		print('record: ')
		print('ass_id: ', ass_id, ' worker_id: ', worker_id)
		
		if (multiple_attempts_true == '1'):
			print('\n  ---- worker recording (failed the first time) -----')
		else:
			print('\n  ---- worker recording for', battery_name, '(new) -----')
		scripts.print_row('assignmentId:', ass_id)
		scripts.print_row('workerId:', worker_id)
		scripts.print_row('test:', test_idx)
		scripts.print_row('question:', question_idx)
		
		return render_template(record_template,
			error=multiple_attempts_true,
			proctor=proctor_name,
			battery=battery_name,
			test=test_idx,
			question=question_idx,
			questionIdx1Based=str(int(question_idx)+1),
			numQuestions=n,
			assignmentId=ass_id,
			hitId='',
			turkSubmitTo='',
			workerId=worker_id,
			is_not_preview=True)
	else:
		return abort(404)


# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# STEP 2: upload user input
# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
@app.route('/<proctor_name>/<battery_name>/upload-voice/<test_idx>/<question_idx>', methods=['GET', 'POST'])
def upload(proctor_name, battery_name, test_idx, question_idx):
	if proctor_name == 'turk':
		ass_id, hit_id, submit_path, worker_id, arg_string = scripts.get_args()

		print('upload: ')
		print('ass_id: ', ass_id, ' hit_id: ', hit_id, ' submit_path: ', ' worker_id: ', worker_id)
		filename = os.path.join(save_location, env, worker_id + "_" + ass_id + "_worker_recording.wav")
		print('  workerId:', worker_id, 'recorded. uploading to file ' + filename +'...')
		os.makedirs(os.path.dirname(filename), exist_ok=True)
		print('  request.files:',request.files)
		audio_data = request.files['audio_data']
		print('  saving to',filename,'...')
		audio_data.save(filename)			# save original file
		#y, sr = librosa.load(filename, sr=16000)	# downsample to 16kHz
		#os.remove(filename)				# remove original
		#os.rename(filename, filename.rstrip('.wav') + '_original.wav')
		#sf.write(filename, y, sr)	
		print('  workerId:', worker_id, '...upload complete.')

		return ('', 202)
	elif proctor_name == 'appen':
		ass_id, worker_id, arg_string = scripts.get_args('appen')

		print('upload: ')
		print('ass_id: ', ass_id, ' worker_id: ', worker_id)
		filename = os.path.join(save_location, env, worker_id + "_" + ass_id + "_worker_recording.wav")
		print('  workerId:', worker_id, 'recorded. uploading to file ' + filename +'...')
		os.makedirs(os.path.dirname(filename), exist_ok=True)
		print('  request.files:',request.files)
		audio_data = request.files['audio_data']
		print('  saving to',filename,'...')
		audio_data.save(filename)			# save original file
		#y, sr = librosa.load(filename, sr=16000)	# downsample to 16kHz
		#os.remove(filename)				# remove original
		#os.rename(filename, filename.rstrip('.wav') + '_original.wav')
		#sf.write(filename, y, sr)	
		print('  workerId:', worker_id, '...upload complete.')

		return ('', 202)
	else:
		return abort(404)

# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# STEP 3: validate user input
# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
@app.route('/<proctor_name>/<battery_name>/validate-voice/<test_idx>/<question_idx>', methods=['GET', 'POST'])
def validate(proctor_name, battery_name, test_idx, question_idx):
	if proctor_name == 'turk':
		ass_id, hit_id, submit_path, worker_id, arg_string = scripts.get_args()

		print('validate: ')
		print('ass_id: ', ass_id, ' hit_id: ', hit_id, ' submit_path: ', ' worker_id: ', worker_id)
		print('\n  workerId:', worker_id, 'validating...')

		# validation 1: transcribe worker-uploaded audio file
		filename = os.path.join(save_location,env,worker_id+"_"+ass_id+"_worker_recording.wav")
		try:
			transcript = scripts.val1(filename)
		except FileNotFoundError:
			return redirect('/' + proctor_name + '/' + battery_name + '/record-voice/' + test_idx + '/' + question_idx + '/1' + arg_string)
		print('    transcript: ' + transcript)

		# validation 1a: count number of words transcribed; accept/reject based on # words threshold
		# validation 1b: measure length of audio file; accept/reject based on length threshold
		# output True iff pass val1a and val1b
		# save in user's specific accept_hit gradesheet
		test_numwords = scripts.val1a(transcript, 15)
		test_soundlength = scripts.val1b(filename, 5)
		print('    val1a (numwords): ' + str(test_numwords))
		print('    val1b (soundlength): ' + str(test_soundlength))
		#session[ass_id + "_" + question_idx] = test_numwords & test_soundlength# & (test_wer < 0.2)
		session[ass_id + "_" + question_idx] = test_soundlength & test_numwords & test_soundlength
		print("    worker passes this task:",session[ass_id + "_" + question_idx])

		if not session[ass_id + "_" + question_idx]:
			return redirect('/' + proctor_name + '/' + battery_name + '/record-voice/' + test_idx + '/' + question_idx + '/1' + arg_string)
		else:
			entrainment_config_filename = os.path.join(save_location,env,worker_id+"_"+ass_id+"_entrainment_config.txt")
			with open(entrainment_config_filename, 'r') as entrainment_handle:
				entrainment_config = entrainment_handle.readlines()[0].strip('\n')
			entrainment_config = literal_eval(entrainment_config)
			try:
				experiment.main(save_location, env, worker_id, ass_id, entrainment_config)
			except Exception as e:
				return redirect('/' + proctor_name + '/' + battery_name + '/record-voice/' + test_idx + '/' + question_idx + '/1' + arg_string)
			print('  workerId:', worker_id, 'redirecting...')
			return redirect('/' + proctor_name + '/' + battery_name + '/evaluate/' + test_idx + '/' + question_idx + arg_string)
	elif proctor_name == 'appen':
		ass_id, worker_id, arg_string = scripts.get_args('appen')

		print('validate: ')
		print('ass_id: ', ass_id, ' worker_id: ', worker_id)
		print('\n  workerId:', worker_id, 'validating...')

		# validation 1: transcribe worker-uploaded audio file
		filename = os.path.join(save_location,env,worker_id+"_"+ass_id+"_worker_recording.wav")
		try:
			transcript = scripts.val1(filename)
		except FileNotFoundError:
			return redirect('/' + proctor_name + '/' + battery_name + '/record-voice/' + test_idx + '/' + question_idx + '/1' + arg_string)
		print('    transcript: ' + transcript)

		# validation 1a: count number of words transcribed; accept/reject based on # words threshold
		# validation 1b: measure length of audio file; accept/reject based on length threshold
		# output True iff pass val1a and val1b
		# save in user's specific accept_hit gradesheet
		test_numwords = scripts.val1a(transcript, 15)
		test_soundlength = scripts.val1b(filename, 5)
		print('    val1a (numwords): ' + str(test_numwords))
		print('    val1b (soundlength): ' + str(test_soundlength))
		#session[ass_id + "_" + question_idx] = test_numwords & test_soundlength# & (test_wer < 0.2)
		session[ass_id + "_" + question_idx] = test_soundlength & test_numwords & test_soundlength
		print("    worker passes this task:",session[ass_id + "_" + question_idx])

		entrainment_config_filename = os.path.join(save_location,env,worker_id+"_"+ass_id+"_entrainment_config.txt")
		with open(entrainment_config_filename, 'r') as entrainment_handle:
			entrainment_config = entrainment_handle.readlines()[0].strip('\n')
		entrainment_config = literal_eval(entrainment_config)
		try:
			experiment.main(save_location, env, worker_id, ass_id, entrainment_config)
		except Exception as e:
			return redirect('/' + proctor_name + '/' + battery_name + '/record-voice/' + test_idx + '/' + question_idx + '/1' + arg_string)
		print('  workerId:', worker_id, 'redirecting...')
		return redirect('/' + proctor_name + '/' + battery_name + '/evaluate/' + test_idx + '/' + question_idx + arg_string)
	else:
		return abort(404)

# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# STEP 4: evaluate synthesized response
# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
@app.route('/<proctor_name>/<battery_name>/evaluate/<test_idx>/<question_idx>', methods=['GET', 'POST'])
def evaluate(proctor_name, battery_name, test_idx, question_idx):
	if proctor_name == 'turk':
		ass_id, hit_id, submit_path, worker_id, arg_string = scripts.get_args()

		print('evaluate: ')
		print('ass_id: ', ass_id, ' hit_id: ', hit_id, ' submit_path: ', ' worker_id: ', worker_id)
		audioFile = worker_id + "_" + ass_id + "_synthesized.wav"
		audioURL = 'https://percepteval.net' + '/' + audioFile
		print(audioURL)
		submitEvaluation = '/' + proctor_name + '/' + battery_name + '/thanks/' + test_idx + '/' + question_idx + arg_string
		trait_config_filename = os.path.join(save_location,env,worker_id+"_"+ass_id+"_entrainment_config.txt")
		with open(trait_config_filename, 'r') as trait_handle:
			perceptualTrait = trait_handle.readlines()[0].strip('\n')
		return render_template(evaluation_template,
			submitEvaluation=submitEvaluation,
			audioURL=audioURL,
			perceptualTrait=perceptualTrait
		)
	elif proctor_name == 'appen':
		ass_id, worker_id, arg_string = scripts.get_args('appen')

		print('evaluate: ')
		print('ass_id: ', ass_id, ' worker_id: ', worker_id)
		audioFile = worker_id + "_" + ass_id + "_synthesized.wav"
		audioURL = 'https://percepteval.net' + '/' + audioFile
		print(audioURL)
		submitEvaluation = '/' + proctor_name + '/' + battery_name + '/thanks/' + test_idx + '/' + question_idx + arg_string
		trait_config_filename = os.path.join(save_location,env,worker_id+"_"+ass_id+"_trait_config.txt")
		with open(trait_config_filename, 'r') as trait_handle:
			perceptualTrait = trait_handle.readlines()[0].strip('\n')
		return render_template(evaluation_template,
			submitEvaluation=submitEvaluation,
			audioURL=audioURL,
			perceptualTrait=perceptualTrait
		)
	else:
		return abort(404)

# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# STEP 5: data collection complete (if applicable, tell mturk that worker is done), submit to mTurk
# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
@app.route('/<proctor_name>/<battery_name>/thanks/<test_idx>/<question_idx>', methods=['GET', 'POST'])
def complete(proctor_name, battery_name, test_idx, question_idx):
	if proctor_name == 'turk':
		selected_option = request.form.get('option')
		print('selected_option: ', selected_option)

		ass_id, hit_id, submit_path, worker_id, arg_string = scripts.get_args()


		score_file = os.path.join(save_location, env, worker_id + "_" + "score.txt")
		with open(score_file, 'w') as score_handle:
			score_handle.write(selected_option + '\n')

		# final thanks + instructions for worker
		print('    workerId:', worker_id, 'done with all questions for test', test_idx,'of',battery_name + '.')	

		print('  ---- task complete -------------')
		###
		submit_link = 'https://www.mturk.com/mturk/externalSubmit' if (env == 'production') else 'https://workersandbox.mturk.com/mturk/externalSubmit'

		localtime = time.asctime(time.localtime(time.time()))
		worker_ip = request.environ['REMOTE_ADDR']
		try:
			ip_loc = iplocator.city(worker_ip)
			worker_country = "%s (%s)" % (ip_loc.country.name, ip_loc.country.iso_code)
			worker_region = "%s (%s)" % (ip_loc.subdivisions.most_specific.name, ip_loc.subdivisions.most_specific.iso_code)
			worker_city = ip_loc.city.name
		except Exception:
			worker_country = "N/A"
			worker_region = "N/A"
			worker_city = "N/A"

		elapsed_time = time.time() - session.get(ass_id + "_starttime", 0)
		probably_not_fraud = True if (elapsed_time > 10) else False

		payload = {	'hitId':hit_id, 'assignmentId':ass_id, 'workerId':worker_id, 'turkSubmitTo':submit_link, 'environment':env,
				'datetime_completed':localtime, 'elapsed_time':elapsed_time, 'probably_not_fraud':str(probably_not_fraud),
				'worker_ip':worker_ip, 'worker_country':worker_country, 'worker_region':worker_region, 'worker_city':worker_city}

		print('final payload:',payload)
		submit_link = 'https://www.mturk.com/mturk/externalSubmit' if (env == 'production') else 'https://workersandbox.mturk.com/mturk/externalSubmit'

		session.clear()
		print('session cleared. ready to submit.')
		print('  ---- task complete -------------')

		turk_submit_final = submit_link + '?' + urllib.parse.urlencode(payload)
		###
		return redirect(turk_submit_final)
	elif proctor_name == 'appen':
		selected_option = request.form.get('option')
		print('selected_option: ', selected_option)

		ass_id, worker_id, arg_string = scripts.get_args('appen')

		score_file = os.path.join(save_location, env, worker_id + "_" + "score.txt")
		with open(score_file, 'w') as score_handle:
			score_handle.write(selected_option + '\n')

		# final thanks + instructions for worker
		print('    workerId:', worker_id, 'done with all questions for test', test_idx,'of',battery_name + '.')	

		print('  ---- task complete -------------')

		localtime = time.asctime(time.localtime(time.time()))
		worker_ip = request.environ['REMOTE_ADDR']
		try:
			ip_loc = iplocator.city(worker_ip)
			worker_country = "%s (%s)" % (ip_loc.country.name, ip_loc.country.iso_code)
			worker_region = "%s (%s)" % (ip_loc.subdivisions.most_specific.name, ip_loc.subdivisions.most_specific.iso_code)
			worker_city = ip_loc.city.name
		except Exception:
			worker_country = "N/A"
			worker_region = "N/A"
			worker_city = "N/A"

		elapsed_time = time.time() - session.get(ass_id + "_starttime", 0)
		pickle_file_path = os.path.join(save_location, env, worker_id + "_" + ass_id + "_endtime" ".pickle")
		with open(pickle_file_path, "wb") as file:
			pickle.dump(time.time(), file)
		probably_not_fraud = True if (elapsed_time > 10) else False

		payload = {	'assignmentId':ass_id, 'workerId':worker_id, 'environment':env,
				'datetime_completed':localtime, 'elapsed_time':elapsed_time, 'probably_not_fraud':str(probably_not_fraud),
				'worker_ip':worker_ip, 'worker_country':worker_country, 'worker_region':worker_region, 'worker_city':worker_city}

		print('final payload:',payload)

		session.clear()
		print('session cleared. ready to submit.')
		print('  ---- task complete -------------')

		nextPage = '/' + proctor_name + '/' + battery_name + '/code/' + test_idx + '/' + question_idx + arg_string
		###
		return redirect(nextPage)
	else:
		abort(404)

# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# STEP 6: Display code
# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
@app.route('/<proctor_name>/<battery_name>/code/<test_idx>/<question_idx>', methods=['GET', 'POST'])
def display_code(proctor_name, battery_name, test_idx, question_idx):
	if proctor_name == 'appen':
		ass_id, worker_id, arg_string = scripts.get_args('appen')
		
		with open('codes.pickle', 'rb') as f:
			# Load the set from the file
			codes = pickle.load(f)
		code_displayed_to_worker = codes.pop()
		with open(worker_id + '_' + ass_id + '.txt', 'w') as wf:
			wf.write(code_displayed_to_worker)
		return render_template(code_template,
			code=code_displayed_to_worker
		)
	else:
		return abort(404)

# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
if __name__ == '__main__':
	# path to ssl certs goes here
	app.run(host='0.0.0.0', port=5000, ssl_context=(cer, key))

