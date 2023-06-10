# deploy mturk HIT accepting voice recording from worker
# author: chris song

import boto3, urllib3
from init import init, yes_no
import argparse
import json
import os.path
import uuid
import json

# ---------------------------------------------------------------------------------------
# deploy HIT
# ---------------------------------------------------------------------------------------

def deployHITs(client, preview_url, start_index, end_index, logdir):

    file_uuid = uuid.uuid4()
    logfile = os.path.join(logdir, 'launched_%s.json' % (file_uuid))

    if os.path.exists(logfile):
        to_continue = yes_no('This set of HITs appears to have already been launched. Continue? (y/n)')
        if not to_continue:
            print('Aborting')
            return
        else:
            print('Launching HITs, existing logfile will be overwritten')
    # -------------------------------------------------------------------------------
    # HIT metadata
    # -------------------------------------------------------------------------------
    TaskAttributes = {
        'MaxAssignments': 27,
        'LifetimeInSeconds': 30 * 60 * 60 * 24,
        'AssignmentDurationInSeconds': 10 * 60,
        'Reward': '5.00',
        'Title': 'Record yourself describing this week\'s weather',
        'Keywords': 'sound, label, read, record, voice',
        'Description': 'Submit an audio recording of yourself describing this week\'s weather.',
        'QualificationRequirements': [
            {
                'QualificationTypeId': '00000000000000000071',
                'Comparator': 'EqualTo',
                'LocaleValues': [{'Country': 'US'}],
                'ActionsGuarded': 'DiscoverPreviewAndAccept'
            },
            {
                'QualificationTypeId': '000000000000000000L0',
                'Comparator': 'GreaterThan',
                'IntegerValues': [90],
                'ActionsGuarded': 'DiscoverPreviewAndAccept'
            }
        ]
    }
    
    # -------------------------------------------------------------------------------
    # task prompts to be given in HITs
    # -------------------------------------------------------------------------------
    # general xml payload template
    # external task url is in here, with ${idx} in place of index
    question_xml =  """<ExternalQuestion xmlns="http://mechanicalturk.amazonaws.com/AWSMechanicalTurkDataSchemas/2006-07-14/ExternalQuestion.xsd">
            <ExternalURL>${flask_url}/turk/${battery}/${idx}</ExternalURL>
            <FrameHeight>0</FrameHeight>
            </ExternalQuestion>"""

    for r in (("${flask_url}", flask_url), ("${battery}", battery)):
        question_xml = question_xml.replace(*r)

    # -------------------------------------------------------------------------------
    # HIT creations
    # -------------------------------------------------------------------------------
    hit_id_to_idx = {}
    hit_type_id = ''

    launched_hits = []

    num_launched = 0

    # loop through each sound
    for i in range(start_index,end_index):
        # prepare xml payload customized w/test idx
        question_enc = question_xml.replace('${idx}',str(i))

        # create hit using xml payload and task attributes
        hit = client.create_hit(**TaskAttributes,Question=question_enc)

        # save HIT type id for later
        hit_type_id = hit['HIT']['HITTypeId']

        # save hit_id-to-test-idx mappings
        hit_id_to_idx[hit['HIT']['HITId']] = i

        launched_hits.append(hit)

        num_launched += 1

    print('Launched %d HITs...' % num_launched)
    print(' ')

    # print hit_id-to-sound mappings
    #for key,value in hit_id_to_idx.items():
    #    print("  %-30s %30s" % (key, value))

    print("You can view the HITs here:")
    print(preview_url + "?groupId={}".format(hit_type_id))
    print(' ')

    log_dict = {'attributes':TaskAttributes, 'hit_id_to_idx':hit_id_to_idx}

    with open(logfile, 'w') as fp:
        json.dump(log_dict, fp)

    print('HIT logfile saved at %s' % logfile)

def deploy_sqs_items():
    sqs = boto3.client('sqs', region_name='us-east-1')
    queue_url = 'https://sqs.us-east-1.amazonaws.com/180367849334/percept_eval_deployment_queue'
    list1 = ['entrain-pitch', 'entrain-volume']
    list2 = ['entrain-pitch', 'disentrain-volume']
    list3 = ['entrain-pitch']
    list4 = ['disentrain-pitch', 'entrain-volume']
    list5 = ['disentrain-pitch', 'disentrain-volume']
    list6 = ['disentrain-pitch']
    list7 = ['entrain-volume']
    list8 = ['disentrain-volume']
    list9 = []
    python_lists = [list1, list2, list3, list4, list5, list6, list7, list8, list9, \
                    list1, list2, list3, list4, list5, list6, list7, list8, list9, \
                    list1, list2, list3, list4, list5, list6, list7, list8, list9]

    sqs = boto3.client('sqs')

    response = sqs.list_queues()

    print(response['QueueUrls'])

    for python_list in python_lists:
        json_string = json.dumps(python_list)
        response = sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=json_string
        )
        print(response)
        
# ---------------------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Deploy a range of HITs')
    parser.add_argument('--logdir', dest='logdir', default='./hit_logs', help='Write the output log to this directory.')
    args = parser.parse_args()
    # parse config info (vars: region, profile, env, flask_url)
    with open("turk_config.txt", "r+") as config:
        for line in config: exec(line)

    # initiate connection to turk server
    client, preview_url = init(region, profile, env)

    # -------------------
    # deploy SQS queue items - author: ben ciaglo
    deploy_sqs_items()
    # -------------------
    # deploy HITs
    deployHITs(client, preview_url, 0, 27, args.logdir)
