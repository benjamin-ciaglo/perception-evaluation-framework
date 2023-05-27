from __future__ import division, print_function
from collections import defaultdict
from scipy.stats import pearsonr
from scipy.signal import resample

import numpy as np
import matplotlib.pyplot as plt
import soundfile as sf
import pyworld as pw
from polly_wrapper import PollyWrapper
import boto3
import re
from pysyllables import get_syllable_count
import os
from shutil import rmtree
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("-f", "--frame_period", type=float, default=5.0)
parser.add_argument("-s", "--speed", type=int, default=1)

EPSILON = 1e-8


def extract_ipus(x_polly, x, time_list):
    bot_adjacent_ipu, human_adjacent_ipu = [], []
    t_polly, t = time_list

    bot_adjacent_ipu = [datapoint for datapoint in x_polly if datapoint > 0]
    human_adjacent_ipu = [datapoint for datapoint in x if datapoint > 0]
    return bot_adjacent_ipu, human_adjacent_ipu


def savefig(filename, fig_list, time_list, log=True):
    n = len(fig_list)
    f = fig_list[0]
    x_polly, x = fig_list[0], fig_list[1]

    bot_adjacent_ipu, human_adjacent_ipu = extract_ipus(x_polly, x, time_list)

    if len(bot_adjacent_ipu) > len(human_adjacent_ipu):
        human_adjacent_ipu = resample(human_adjacent_ipu, len(bot_adjacent_ipu))
    elif len(human_adjacent_ipu) > len(bot_adjacent_ipu):
        bot_adjacent_ipu = resample(bot_adjacent_ipu, len(human_adjacent_ipu))

    correlation = pearsonr(bot_adjacent_ipu, human_adjacent_ipu)
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
            plt.imshow(x.T, origin='lower', interpolation='none', aspect='auto', extent=(0, x.shape[0], 0, x.shape[1]))
    else:
        raise ValueError('Input dimension must < 3.')

    plt.savefig(filename)
    plt.close()
    return bot_adjacent_ipu, human_adjacent_ipu


def main(args):
    if os.path.isdir('test'):
        rmtree('test')
    os.mkdir('test')

    filename_to_text = defaultdict(str)
    file_handle = open('text.txt', 'r')
    for line in file_handle:
        split_line = line.split('\t')
        filename, text = split_line[0], split_line[1]
        filename_to_text[filename] = text

    directory = 'test_samples'
    ipu_pairs = []
    p_values = []
    bot_adjacent_ipus = []
    human_adjacent_ipus = []
    for filename in os.listdir(directory):
        f = os.path.join(directory, filename)
        if not os.path.isfile(f):
            continue
        if 'wav' not in f:
            continue
        speech_file_name = directory + '/synthesized_responses/' + filename.split('.')[0] + '.mp3'
        # if os.path.isfile(speech_file_name):
        # continue
        x, fs = sf.read(f)
        f0, t = pw.harvest(x, fs, f0_floor=80.0, f0_ceil=270,
                           frame_period=args.frame_period)

        f0_no_zeroes = [datapoint for datapoint in f0 if datapoint > 0]
        mean_f0 = np.mean(f0_no_zeroes)
        #f0_no_zeroes = list(reversed(f0_no_zeroes))

        f0_diff_sequence = [x - mean_f0 for x in f0_no_zeroes]
        f0_mean_sequence = [(x + mean_f0) / 2 for x in f0_no_zeroes]
        f0_percent_change_sequence = [(x / f0_mean_sequence[i]) * 100 for i, x in enumerate(f0_diff_sequence)]

        sentence = filename_to_text[filename]
        split_sentence = sentence.split(' ')
        stripped_split_sentence = [re.sub(r'\W+', '', word) for word in split_sentence if word]
        syllable_counts = [get_syllable_count(word) if get_syllable_count(word) is not None else
                           get_syllable_count(split_sentence[i]) for i, word in enumerate(stripped_split_sentence)]

        total_syllables = sum(syllable_counts)
        datapoints_per_syllable = len(f0_percent_change_sequence) / total_syllables

        start_index = 0
        text_response = '<speak>'
        response = "I appreciate your comprehensive weather summary. " + \
            "It's interesting to hear the changes from last week to this week. " + \
            "Do you find these changes affect your daily routines?"
        split_response = response.split(' ')
        stripped_split_response = [re.sub(r'\W+', '', word) for word in split_response if word]
        syllable_counts_response = [get_syllable_count(word) if get_syllable_count(word) is not None else
                           get_syllable_count(split_response[i]) for i, word in enumerate(stripped_split_response)]
        total_syllables_response = sum(syllable_counts_response)
        datapoints_per_syllable_response = len(f0_percent_change_sequence) / total_syllables_response

        for i, word in enumerate(stripped_split_response):
            syllables = syllable_counts_response[i]
            end_index = start_index + int(syllables * datapoints_per_syllable_response)
            avg_percent_diff = np.average([datapoint for datapoint in f0_percent_change_sequence[start_index:end_index]])
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
            speech_file_name = directory + '/synthesized_responses/' + filename.split('.')[0] + '.mp3'
            speech_text_file_name = directory + '/synthesized_responses_text/' + filename.split('.')[0] + '.txt'
            with open(speech_file_name, 'wb') as speech_file:
                speech_file.write(audio_stream.read())
            with open(speech_text_file_name, 'w') as speech_text_file:
                speech_text_file.write(text_response)

            x_polly, fs_polly = sf.read(speech_file_name)
            f0_polly, t_polly = pw.harvest(x_polly, fs_polly, f0_floor=80.0, f0_ceil=370.0,
                                           frame_period=args.frame_period)

            bot_adjacent_ipu, human_adjacent_ipu = savefig('comparison/f0_' + filename + '.png', [f0_polly, f0], [t_polly, t])
            bot_adjacent_ipus += [bot_adjacent_ipu]
            human_adjacent_ipus += [human_adjacent_ipu]

        print(speech_file_name + ' entrained.. ')
    print('Loop complete. Check /comparison directory.')

    file_handle = open('correlation_results.txt', 'w')
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


if __name__ == '__main__':
    args = parser.parse_args()
    main(args)
