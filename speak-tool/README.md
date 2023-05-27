# Speak: a toolkit to collect speech recordings from Amazon Mechanical Turk workers
Christopher Song, David Harwath, Tuka Alhanai, James Glass
(README last updated by Christopher Song 21 July 2022)

 - Overview
 - Setup/Instructions
 - Methods
 - Acknowledgements

**For more information on the design of Speak, please refer to [this paper in LREC 2022](http://www.lrec-conf.org/proceedings/lrec2022/pdf/2022.lrec-1.787.pdf).**

**If you end up using Speak, I'd love to hear about it! Find me on LinkedIn and shoot me a message. Any [citations](http://www.lrec-conf.org/proceedings/lrec2022/bib/2022.lrec-1.787.bib) in your academic work are also appreciated.**



## Overview
This toolkit allows requesters to collect speech recordings from workers on Amazon Mechanical Turk (AMT), by posting tasks to AMT using the boto3 ExternalQuestion data structure. Each webpage prompts a worker with a stimulus (image, text, sound, etc.) and uses an embedded audio recorder to collect the worker's speech recordings. Importantly, the collected data is validated before storage.

This toolkit consists of two distinct tools:
 - [A Flask web application](main.py), which hosts the website through which workers record their answers to tasks
 - [A suite of AMT scripts](mturk/), which allows a requester to deploy/review/delete HITs that direct workers to the Flask web application

These tools are used together in order to accomplish the following tasks:
1. **Upload** (Flask app): deploy the task prompts + audio recorder on a website (with a unique link for each task)
2. **Deploy** (AMT scripts): embed each task link in an ExternalQuestion, and launch HITs for each ExternalQuestion
3. **Collect** (Flask app): save worker recordings to a location on the web server, in an organized manner
4. **Transcribe** (Flask app): save transcripts of worker recordings, using a speech transcription API of your choice (default: Google SpeechRecognition API)
5. **Validate** (Flask app): ensure that the data collected is useful, and that workers are completing tasks properly
6. **Document** (Flask app, AMT scripts): log the metadata for each task, including AMT worker info, prompt info, and data locations
7. **Review** (AMT scripts): review HITs, automatically approve those which are unlikely to be fraudulent, log those which require further investigation, and reject them as needed

Each of these steps is described in detail further below in the README.

This tool is intended to be used in conjunction with WSGI (to support multiple instances of the app at once, so that many workers can submit recordings concurrently) and nginx (for SSL certificates, because HTTPS is required by AMT)

## Application Setup
1. Clone this repository.
2. Ensure that you have the AWS credentials file linked to your AMT account. It should be located in `~/.aws/credentials` and have the following format:
```
[username]
aws_access_key_id = ACCESS_KEY_ID_HERE
aws_secret_access_key = SECRET_ACCESS_KEY_HERE
```
3. Using virtualenv or conda, create a virtual environment and activate it. Install all of the packages outlined in `requirements.txt`.
4. Set up an nginx proxy server on your machine secured with a SSL certificate.
4. Obtain an SSL certificate for your machine. (Amazon does not allow ExternalQuestion HITs to direct workers to non-HTTPS enabled websites.)
5. Put the images you want to collect captions for in the 'images' directory. If there are a large number of them, consider using a symbolic link instead.
6. Generate a text file containing a relative path (from the tool's base directory) to each image file, separated by a linebreak. Example:
```
images/d/dining_room/gsun_2cfa50e4b8eab1d67a53bb20aaa28021.jpg
images/a/abbey/gsun_20086d50e070ae7560403aa409461895.jpg
...
```
Make sure that the lines of this text file are shuffled randomly (e.g. by using shuf), because they will be served to workers in the order they appear in the file.

7. Edit the template files in `templates/` if you would like to change the format of the task or the instructions displayed to the workers.

8. For automated extraction of geolocation data from participant IP addresses, download the [GeoLite2 database](https://dev.maxmind.com/geoip/geolite2-free-geolocation-data?lang=en), and place the GeoLite2-City.mmdb file in `./scripts/geolite2`. (Due to filesize restrictions, the folder currently only contains the README, license, and copyright information.

9. Edit the configuration files (`app_config.txt` and `mturk/turk_config.txt`) according to your project (account info, file locations, etc.). In app_config.txt, be sure to point the "input_files" variable to the text file you created in step 6.

## WSGI setup
You should not have to edit the WSGI configuration. However, for posterity the guide that I followed to set up WSGI for this task can be found at

https://www.digitalocean.com/community/tutorials/how-to-serve-flask-applications-with-uswgi-and-nginx-on-ubuntu-18-04

## nginx Setup
1. Install nginx and secure it with an SSL certificate. A simple tutorial that uses a free certificate service is outlined here:
https://www.digitalocean.com/community/tutorials/how-to-serve-flask-applications-with-uswgi-and-nginx-on-ubuntu-18-04

2. Edit the default configuration in the `/etc/nginx/sites-available` folder to include a WSGI pass block that points to the .sock file that will be created by WSGI. This should look something like this:
```
location / {
        include uwsgi_params;
        uwsgi_pass unix:/data/sls/u/dharwath/code/speak_tool_instances/image_caption_template/image_caption_task.sock;
     }
```
Where the path provided to uwsgi_pass points to the directory that the server code lives in on your filesystem.

An example configuration file is located in `example_nginx_config`; you will need to change the hostname from arcas to whatever the name is of the computer that you are using.

3. Edit the `/etc/nginx/nginx.conf` file to include the configuration line
```
client_max_body_size 3M
```
This will prevent the client from throwing a "413 Request Entity Too Large" error when the recording is too large. (Thanks to Rami Manna for this tip)

4. Verify that a symlink to your site configuration file (e.g. `/etc/nginx/sites-available/default`) exists in `/etc/nginx/sites-enabled/`

## Use

1. Activate the virtual environment you created in Setup step 3.
2. Launch the app with WSGI with
```
$ uwsgi --ini wsgi.ini
```
The application server should now be up and running; the next step is to deploy HITs to AMT.

3. Edit the parameters in the TaskAttributes structure in the mturk/1_deploy-hit.py file. This is where you have the opportunity to change the HIT pay, requirements that workers must satisfy, the task description, how much worker redundancy you want per HIT, etc.

4. Verify that the `flask_url` variable in the `mturk/turk_config.txt` file points to the URL specified in your nginx site configuration file (e.g. `/etc/nginx/sites-available/default`).

5. Run the `mturk/1_deploy-hit.py` file with the start and end indices of the HITs you want to deploy. The number of total HITs you can deploy is the number of lines in the file containing the input image paths divided by the number of images that are displayed per HIT (controlled by the `n` variable in the `app_config.txt` file). Typically, you should only launch several hundred or perhaps a thousand HITs at one time. As far as `mturk/1_deploy-hit.py` is concerned, the HIT indexed at 1 will display the first n images from the input list, the 2nd HIT will display the 2nd n images, and so on. The `1_deploy-hit.py` file will also create a log file or "receipt" for the HITs that you launched, by default stored in the `hit_logs` directory. You can pass this file as an argument to the rest of the tools in the `mturk/` folder, so that the tools for retrieving HITs, approving results, etc. know which batch of HITs they should operate on.

6. The rest of the tools in the `mturk/` folder are relatively self-explainatory. The main other tool you will often use besides `1_deploy-hit.py` is `3a_autoreview-hits.py`, which will automatically accept any HITs that were successfully recorded and met the WER requirements set in `scripts/validation.py`.

7. .wav files are stored in the directory specified in the `app_config.txt` file. The metadata for each HIT (which you can use to find the image file described by each .wav file along with other information, such as the speaker's worker ID, location data, etc.) is found in the `production/turk_data/worker_log.csv` file under that directory. This file is appended whenever a HIT is approved by `3a_autoreview-hits.py`.
