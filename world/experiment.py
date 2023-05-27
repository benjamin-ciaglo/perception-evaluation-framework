"""."""
from __future__ import division, print_function
import argparse
import re
import os
from scipy.stats import pearsonr
from scipy.signal import resample

import numpy as np
import matplotlib.pyplot as plt
import soundfile as sf
import pyworld as pw
from world.polly_wrapper import PollyWrapper
import boto3
from pysyllables import get_syllable_count

parser = argparse.ArgumentParser()
parser.add_argument("-f", "--frame_period", type=float, default=5.0)
parser.add_argument("-s", "--speed", type=int, default=1)

EPSILON = 1e-8


def extract_ipus(x_polly, x_var):
    """."""
    bot_adjacent_ipu, human_adjacent_ipu = [], []

    bot_adjacent_ipu = [datapoint for datapoint in x_polly if datapoint > 0]
    human_adjacent_ipu = [datapoint for datapoint in x_var if datapoint > 0]
    return bot_adjacent_ipu, human_adjacent_ipu


def savefig(filename, fig_list, log=True):
    """."""
    n = len(fig_list)
    f = fig_list[0]
    x_polly, x = fig_list[0], fig_list[1]

    bot_adjacent_ipu, human_adjacent_ipu = extract_ipus(x_polly, x)

    if len(bot_adjacent_ipu) > len(human_adjacent_ipu):
        human_adjacent_ipu = resample(human_adjacent_ipu, len(bot_adjacent_ipu))
    elif len(human_adjacent_ipu) > len(bot_adjacent_ipu):
        bot_adjacent_ipu = resample(bot_adjacent_ipu, len(human_adjacent_ipu))

    if len(f.shape) == 1:
        plt.figure()
        for i, f in enumerate(fig_list):
            plt.subplot(n, 1, i + 1)
            if len(f.shape) == 1:
                plt.plot(f)
                plt.xlim([0, len(f)])
    elif len(f.shape) == 2:
        plt.figure()
        for i, f in enumerate(fig_list):
            plt.subplot(n, 1, i + 1)
            if log:
                x = np.log(f + EPSILON)
            else:
                x = f + EPSILON
            plt.imshow(x.T, origin='lower', \
                interpolation='none', aspect='auto', extent=(0, x.shape[0], 0, x.shape[1]))
    else:
        raise ValueError('Input dimension must < 3.')

    plt.savefig(filename)
    plt.close()
    return bot_adjacent_ipu, human_adjacent_ipu


def main(save_location, env, worker_id, ass_id):
    """."""
    transcript_filename = os.path.join(save_location, env, \
                                       worker_id + "_" + ass_id + "_worker_transcript.txt")
    wav_filename = os.path.join(save_location,env,worker_id+"_"+ass_id+"_worker_recording.wav")
    print(transcript_filename)
    bot_adjacent_ipus = []
    human_adjacent_ipus = []

    speech_file_name = os.path.join(save_location, env, worker_id + "_" + ass_id + ".mp3")
    x_var, fs_var = sf.read(wav_filename)
    f0_var = pw.harvest(x_var, fs_var, f0_floor=80.0, f0_ceil=270)[0]

    f0_no_zeroes = [datapoint for datapoint in f0_var if datapoint > 0]
    mean_f0 = np.mean(f0_no_zeroes)
    #f0_no_zeroes = list(reversed(f0_no_zeroes))

    f0_diff_sequence = [x - mean_f0 for x in f0_no_zeroes]
    f0_mean_sequence = [(x + mean_f0) / 2 for x in f0_no_zeroes]
    f0_percent_change_sequence = [(x / f0_mean_sequence[i]) * 100 for i, \
                                  x in enumerate(f0_diff_sequence)]

    start_index = 0
    text_response = '<speak>'
    response = "I appreciate your comprehensive weather summary. " + \
        "It's interesting to hear the changes from last week to this week. " + \
        "Do you find these changes affect your daily routines?"
    split_response = response.split(' ')
    stripped_split_response = [re.sub(r'\W+', '', word) for word in split_response if word]
    syllable_counts_response = [get_syllable_count(w) if get_syllable_count(w) is not None \
        else get_syllable_count(split_response[i]) for i, w in enumerate(stripped_split_response)]
    total_syllables_response = sum(syllable_counts_response)
    datapoints_per_syllable_response = len(f0_percent_change_sequence) / total_syllables_response

    for i in range(0, len(stripped_split_response)):
        syllables = syllable_counts_response[i]
        end_index = start_index + int(syllables * datapoints_per_syllable_response)
        avg_percent_diff = np.average([datapoint for \
            datapoint in f0_percent_change_sequence[start_index:end_index]])
        pitch_tag = round(avg_percent_diff, 0)
        if pitch_tag > 0:
            pitch_tag = '+' + str(pitch_tag)
        else:
            pitch_tag = str(pitch_tag)
        text_response += '<prosody pitch="' + pitch_tag + '%">'
        text_response += split_response[i]
        text_response += '</prosody>'
        start_index = end_index
    text_response += '</speak>'
    polly_object = PollyWrapper(boto3.client('polly'), boto3.resource('s3'))
    results = polly_object.synthesize(text_response, 'standard', 'Joanna', 'mp3', 'en-US', False)
    audio_stream = results[0]

    if audio_stream is not None:
        speech_file_name = os.path.join(save_location, env, \
            worker_id + "_" + ass_id + "_synthesized.mp3")
        speech_text_file_name = os.path.join(save_location, \
            env, worker_id + "_" + ass_id + "_synthesized_transcript.txt")
        with open(speech_file_name, 'wb', encoding='utf-8') as speech_file:
            speech_file.write(audio_stream.read())
        with open(speech_text_file_name, 'w', encoding='utf-8') as speech_text_file:
            speech_text_file.write(text_response)

        x_polly, fs_polly = sf.read(speech_file_name)
        f0_polly = pw.harvest(x_polly, fs_polly, f0_floor=80.0, f0_ceil=270.0)

        bot_adjacent_ipu, human_adjacent_ipu = savefig(os.path.join(save_location, env, \
            worker_id + "_" + ass_id + "_comparison.png"), [f0_polly, f0_var])
        bot_adjacent_ipus += [bot_adjacent_ipu]
        human_adjacent_ipus += [human_adjacent_ipu]

    print(speech_file_name + ' entrained.. ')
    print('Loop complete. Check /comparison directory.')

    file_handle = open(os.path.join(save_location, env, \
        worker_id + "_" + ass_id + "_correlation.txt"), 'w', encoding='utf-8')
    for i, bot_adjacent_ipu in enumerate(bot_adjacent_ipus):
        file_handle.write(str(pearsonr(bot_adjacent_ipu, human_adjacent_ipus[i])[0]) + '\n')
    bot_raw_vals = []
    human_raw_vals = []
    for bot_adjacent_ipu in bot_adjacent_ipus:
        for x in bot_adjacent_ipu:
            bot_raw_vals += [x]
    for human_adjacent_ipu in human_adjacent_ipus:
        for x in human_adjacent_ipu:
            human_raw_vals += [x]
    avg_correlation = pearsonr(bot_raw_vals, human_raw_vals)
    file_handle.write('-------------------\n')
    file_handle.write('Average correlation: ' + str(avg_correlation[0]) + '\n')
