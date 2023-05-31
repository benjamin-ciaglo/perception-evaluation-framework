"""."""
from __future__ import division, print_function
import argparse
import re
import os
import librosa
import subprocess
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
    """Extracts individual pitch units (IPUs) from the data."""
    bot_adjacent_ipu = [datapoint for datapoint in x_polly if datapoint > 0]
    human_adjacent_ipu = [datapoint for datapoint in x_var if datapoint > 0]
    return bot_adjacent_ipu, human_adjacent_ipu

def resample_ipu(bot_adjacent_ipu, human_adjacent_ipu):
    """Resamples IPUs to match their lengths."""
    if len(bot_adjacent_ipu) > len(human_adjacent_ipu):
        human_adjacent_ipu = resample(human_adjacent_ipu, len(bot_adjacent_ipu))
    elif len(human_adjacent_ipu) > len(bot_adjacent_ipu):
        bot_adjacent_ipu = resample(bot_adjacent_ipu, len(human_adjacent_ipu))

    return bot_adjacent_ipu, human_adjacent_ipu

def plot_fig(fig_list, log=True):
    """Plots the figures."""
    n = len(fig_list)
    f = fig_list[0]
    
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
            plt.imshow(x.T, origin='lower', 
                       interpolation='none', aspect='auto', extent=(0, x.shape[0], 0, x.shape[1]))
    else:
        raise ValueError('Input dimension must < 3.')

def save_figure(filename, fig_list, log=True):
    """Saves the figures to a file."""
    x_polly, x = fig_list[0], fig_list[1]

    bot_adjacent_ipu, human_adjacent_ipu = extract_ipus(x_polly, x)
    bot_adjacent_ipu, human_adjacent_ipu = resample_ipu(bot_adjacent_ipu, human_adjacent_ipu)

    plot_fig(fig_list, log)

    plt.savefig(filename)
    plt.close()
    return bot_adjacent_ipu, human_adjacent_ipu

def analyze_speech_pitch(worker_id, ass_id, save_location, env, response, wav_filename, frame_period, entrain=True):
    x_var, fs_var = sf.read(wav_filename)
    if not entrain:
        x_var = x_var[::-1]
    x_var_contiguous = np.ascontiguousarray(x_var)
    f0_var = pw.harvest(x_var_contiguous, fs_var, f0_floor=80.0, f0_ceil=270, frame_period=frame_period)[0]
    f0_no_zeroes = [datapoint for datapoint in f0_var if datapoint > 0]
    mean_f0 = np.mean(f0_no_zeroes)
    f0_diff_sequence = [x - mean_f0 for x in f0_no_zeroes]
    f0_mean_sequence = [(x + mean_f0) / 2 for x in f0_no_zeroes]
    f0_percent_change_sequence = [(x / f0_mean_sequence[i]) * 100 for i, x in enumerate(f0_diff_sequence)]

    split_response = response.split(' ')
    stripped_split_response = [re.sub(r'\W+', '', word) for word in split_response if word]
    syllable_counts_response = [get_syllable_count(w) if get_syllable_count(w) is not None 
                                else get_syllable_count(stripped_split_response[i]) 
                                for i, w in enumerate(stripped_split_response)]
    total_syllables_response = sum(syllable_counts_response)
    datapoints_per_syllable_response = len(f0_percent_change_sequence) / total_syllables_response
    start_index = 0
    text_response = '<speak>'

    for i in range(0, len(split_response)):
        text_response += add_pitch_prosody_tags(start_index, split_response, 
                                          syllable_counts_response, 
                                          f0_percent_change_sequence, 
                                          datapoints_per_syllable_response, i)
        start_index += int(syllable_counts_response[i] * datapoints_per_syllable_response)

    text_response += '</speak>'
    audio_stream = synthesize_speech(text_response, save_location, env, worker_id, ass_id)

    if audio_stream is not None:
        speech_file_name = os.path.join(save_location, env, worker_id + "_" + ass_id + "_synthesized.mp3")
        x_polly, fs_polly = sf.read(speech_file_name)
        f0_polly = pw.harvest(x_polly, fs_polly, f0_floor=80.0, f0_ceil=270.0, frame_period=frame_period)[0]
        bot_adjacent_ipu, human_adjacent_ipu = save_figure(os.path.join(save_location, env, worker_id + "_" + ass_id + "_comparison.png"), [f0_polly, f0_var])

        print(speech_file_name + ' entrained.. ')
        print('Loop complete. Check /comparison directory.')
        write_correlation_data([bot_adjacent_ipu], [human_adjacent_ipu], save_location, env, worker_id, ass_id)

def add_pitch_prosody_tags(start_index, split_response, syllable_counts_response, 
                     f0_percent_change_sequence, datapoints_per_syllable_response, i):
    end_index = start_index + int(syllable_counts_response[i] * datapoints_per_syllable_response)
    avg_percent_diff = np.average([datapoint for datapoint in f0_percent_change_sequence[start_index:end_index]])
    pitch_tag = round(avg_percent_diff, 0)
    pitch_tag = '+' + str(pitch_tag) if pitch_tag > 0 else str(pitch_tag)
    return '<prosody pitch="' + pitch_tag + '%">' + split_response[i] + '</prosody>'

def analyze_speech_amplitude(worker_id, ass_id, save_location, env, response, wav_filename, entrain=True):
    amplitude, sample_rate = librosa.load(wav_filename)
    amplitude_no_zeroes = [datapoint for datapoint in amplitude if datapoint != 0]
    length = len(amplitude_no_zeroes)
    average_first_half = np.mean(np.abs(amplitude_no_zeroes[:length//2]))
    average_second_half = np.mean(np.abs(amplitude_no_zeroes[length//2:]))
    difference = average_second_half - average_first_half

    split_response = response.split(' ')
    stripped_split_response = [re.sub(r'\W+', '', word) for word in split_response if word]
    syllable_counts_response = [get_syllable_count(w) if get_syllable_count(w) is not None 
                                else get_syllable_count(stripped_split_response[i]) 
                                for i, w in enumerate(stripped_split_response)]
    total_syllables_response = sum(syllable_counts_response)

    gradient = np.linspace(average_second_half - difference, average_second_half, total_syllables_response)
    prev_mean_amplitude = 0

    text_response = '<speak>'
    for word, syllables in zip(split_response, syllable_counts_response):
        text_response += add_amplitude_prosody_tags(syllables, word, gradient, prev_mean_amplitude)
        gradient = gradient[syllables:]
        prev_mean_amplitude = np.mean(gradient[:syllables])
    text_response += '</speak>'
    print(text_response)

    audio_stream = synthesize_speech(text_response, save_location, env, worker_id, ass_id)

    if audio_stream is not None:
        save_speech_file(audio_stream, save_location, env, worker_id, ass_id, text_response)
        print('Loop complete. Check /comparison directory.')

def add_amplitude_prosody_tags(syllables, word, gradient, prev_mean_amplitude):
    word_amplitudes = gradient[:syllables]
    mean_amplitude = np.mean(word_amplitudes)
    amplitude_change = mean_amplitude - prev_mean_amplitude
    volume_level = round(amplitude_change, 6)
    volume_level = "+" + str(volume_level) if volume_level >= 0 else str(volume_level)
    return '<prosody volume="' + volume_level + 'dB">' + word + '</prosody>'

def synthesize_speech(text_response, save_location, env, worker_id, ass_id):
    polly_object = PollyWrapper(boto3.client('polly', region_name='us-east-1'), boto3.resource('s3', region_name='us-east-1'))

    results = polly_object.synthesize(text_response, 'standard', 'Joanna', 'mp3', 'en-US', False)
    audio_stream = results[0]

    if audio_stream is not None:
        save_speech_file(audio_stream, save_location, env, worker_id, ass_id, text_response)
    return audio_stream

def save_speech_file(audio_stream, save_location, env, worker_id, ass_id, text_response):
    speech_file_name = os.path.join(save_location, env, worker_id + "_" + ass_id + "_synthesized.mp3")
    speech_text_file_name = os.path.join(save_location, env, worker_id + "_" + ass_id + "_synthesized_transcript.txt")
    with open(speech_file_name, 'wb') as speech_file:
        speech_file.write(audio_stream.read())
    with open(speech_text_file_name, 'w', encoding='utf-8') as speech_text_file:
        speech_text_file.write(text_response)

    wav_filename = os.path.join(save_location, env, worker_id + "_" + ass_id + "_synthesized.wav")
    try:
        # Re-encode MP3 file using ffmpeg
        subprocess.run(["ffmpeg", "-y", "-i", speech_file_name, wav_filename], check=True)
    except subprocess.CalledProcessError as e:
        print(f"An error occurred while re-encoding the MP3 file: {e}")

def write_correlation_data(bot_adjacent_ipus, human_adjacent_ipus, save_location, env, worker_id, ass_id):
    bot_raw_vals = [x for bot_adjacent_ipu in bot_adjacent_ipus for x in bot_adjacent_ipu]
    human_raw_vals = [x for human_adjacent_ipu in human_adjacent_ipus for x in human_adjacent_ipu]
    avg_correlation = pearsonr(bot_raw_vals, human_raw_vals)

    with open(os.path.join(save_location, env, worker_id + "_" + ass_id + "_correlation.txt"), 'w', encoding='utf-8') as file_handle:
        for i, bot_adjacent_ipu in enumerate(bot_adjacent_ipus):
            file_handle.write(str(pearsonr(bot_adjacent_ipu, human_adjacent_ipus[i])[0]) + '\n')
        file_handle.write('-------------------\n')
        file_handle.write('Average correlation: ' + str(avg_correlation[0]) + '\n')
        file_handle.write('p = ' + str(avg_correlation[1]) + '\n')

def generate_response():
    """Generates a response for analysis."""
    response = (
        "I appreciate your comprehensive weather summary. "
        "It's interesting to hear the changes from last week to this week. "
        "Do you find these changes affect your daily routines?"
    )
    return response

def list_words_by_pitch(response, wav_filename, frame_period, entrain=True):
    # Perform pitch analysis
    x_var, fs_var = sf.read(wav_filename)
    if not entrain:
        x_var = x_var[::-1]
    x_var_contiguous = np.ascontiguousarray(x_var)
    f0_var = pw.harvest(x_var_contiguous, fs_var, f0_floor=80.0, f0_ceil=270, frame_period=frame_period)[0]

    f0_no_zeroes = [datapoint for datapoint in f0_var if datapoint > 0]
    mean_f0 = np.mean(f0_no_zeroes)

    f0_diff_sequence = [x - mean_f0 for x in f0_no_zeroes]
    f0_mean_sequence = [(x + mean_f0) / 2 for x in f0_no_zeroes]
    f0_percent_change_sequence = [(x / f0_mean_sequence[i]) * 100 for i, x in enumerate(f0_diff_sequence)]

    split_response = response.split(' ')
    stripped_split_response = [re.sub(r'\W+', '', word) for word in split_response if word]
    syllable_counts_response = [
        get_syllable_count(w) if get_syllable_count(w) is not None else get_syllable_count(split_response[i])
        for i, w in enumerate(stripped_split_response)
    ]
    total_syllables_response = sum(syllable_counts_response)
    datapoints_per_syllable_response = len(f0_percent_change_sequence) / total_syllables_response

    pitch_changes = []
    start_index = 0
    for i in range(len(stripped_split_response)):
        syllables = syllable_counts_response[i]
        end_index = start_index + int(syllables * datapoints_per_syllable_response)
        avg_percent_diff = np.average(f0_percent_change_sequence[start_index:end_index])
        pitch_changes.append(round(avg_percent_diff, 0))
        start_index = end_index

    return pitch_changes


def list_words_by_amplitude(response, wav_filename, entrain=True):
    # Perform amplitude analysis
    amplitude, sample_rate = librosa.load(wav_filename)
    if not entrain:
        amplitude = amplitude[::-1]
    amplitude_no_zeroes = [datapoint for datapoint in amplitude if datapoint != 0]
    length = len(amplitude_no_zeroes)
    average_first_half = np.mean(np.abs(amplitude_no_zeroes[:length // 2]))
    average_second_half = np.mean(np.abs(amplitude_no_zeroes[length // 2:]))

    difference = average_second_half - average_first_half

    split_response = response.split(' ')
    stripped_split_response = [re.sub(r'\W+', '', word) for word in split_response if word]
    syllable_counts_response = [
        get_syllable_count(w) if get_syllable_count(w) is not None else get_syllable_count(split_response[i])
        for i, w in enumerate(stripped_split_response)
    ]
    total_syllables_response = sum(syllable_counts_response)

    amplitude_changes = []
    gradient = np.linspace(average_second_half - difference, average_second_half, total_syllables_response)
    prev_mean_amplitude = 0
    for i in range(len(stripped_split_response)):
        syllables = syllable_counts_response[i]
        word_amplitudes = gradient[:syllables]
        mean_amplitude = np.mean(word_amplitudes)
        amplitude_change = mean_amplitude - prev_mean_amplitude
        amplitude_changes.append(round(amplitude_change, 6))
        gradient = gradient[syllables:]
        prev_mean_amplitude = mean_amplitude

    return amplitude_changes

def synthesize_combined_features(worker_id, ass_id, save_location, env, response, wav_filename, features, frame_period=5):

    if 'entrain-pitch' in features:
        entrain_pitch = True
    else:
        entrain_pitch = False
    if 'entrain-volume' in features:
        entrain_volume = True
    else:
        entrain_volume = False
    pitch_sequence = list_words_by_pitch(response, wav_filename, frame_period, entrain=entrain_pitch)
    volume_sequence = list_words_by_amplitude(response, wav_filename, entrain=entrain_volume)
    
    split_response = response.split(' ')
    stripped_split_response = [re.sub(r'\W+', '', word) for word in split_response if word]
    
    text_response = '<speak>'
    for i in range(len(stripped_split_response)):
        word = split_response[i]
        pitch_change = pitch_sequence[i]
        volume_change = volume_sequence[i]
        
        if pitch_change > 0:
            pitch_change = '+' + str(pitch_change)
        
        if volume_change >= 0:
            text_response += f'<prosody pitch="{pitch_change}%" volume="+{volume_change}dB">{word}</prosody>'
        else:
            text_response += f'<prosody pitch="{pitch_change}%" volume="{volume_change}dB">{word}</prosody>'

    text_response += '</speak>'
    synthesize_speech(text_response, save_location, env, worker_id, ass_id)

def generate_plain_response(worker_id, ass_id, save_location, env, response):
    text_response = '<speak>' + response + '</speak>'
    synthesize_speech(text_response, save_location, env, worker_id, ass_id)

def perform_analysis(worker_id, ass_id, save_location, env, response, wav_filename, features):
    """Performs analysis based on the chosen entrainment features."""
    if 'entrain-pitch' in features and 'entrain-volume' in features:
        synthesize_combined_features(worker_id, ass_id, save_location, env, response, wav_filename, features, frame_period=5)
    elif 'entrain-pitch' in features and 'disentrain-volume' in features:
        synthesize_combined_features(worker_id, ass_id, save_location, env, response, wav_filename, features, frame_period=5)
    elif 'entrain-pitch' in features:
        analyze_speech_pitch(worker_id, ass_id, save_location, env, response, wav_filename, frame_period=5, entrain=True)
    elif 'disentrain-pitch' in features and 'entrain-volume' in features:
        synthesize_combined_features(worker_id, ass_id, save_location, env, response, wav_filename, features, frame_period=5)
    elif 'disentrain-pitch' in features and 'disentrain-volume' in features:
        synthesize_combined_features(worker_id, ass_id, save_location, env, response, wav_filename, features, frame_period=5)
    elif 'disentrain-pitch' in features:
        analyze_speech_pitch(worker_id, ass_id, save_location, env, response, wav_filename, frame_period=5, entrain=False)
    elif 'entrain-volume' in features:
        analyze_speech_amplitude(worker_id, ass_id, save_location, env, response, wav_filename, entrain=True)
    elif 'disentrain-volume' in features:
        analyze_speech_amplitude(worker_id, ass_id, save_location, env, response, wav_filename, entrain=False)
    elif not features:
        generate_plain_response(worker_id, ass_id, save_location, env, response)

def main(save_location, env, worker_id, ass_id, entrainment_features):
    """Performs speech analysis."""
    response = generate_response()
    wav_filename = os.path.join(save_location,env,worker_id+"_"+ass_id+"_worker_recording.wav")
    perform_analysis(worker_id, ass_id, save_location, env, response, wav_filename, entrainment_features)

#main('./', 'sandbox', '1', '1', ['entrain-pitch', 'entrain-volume'])
#main('./', 'sandbox', '2', '2', ['entrain-pitch', 'disentrain-volume'])
#main('./', 'sandbox', '3', '3', ['entrain-pitch'])
#main('./', 'sandbox', '4', '4', ['disentrain-pitch', 'entrain-volume'])
#main('./', 'sandbox', '5', '5', ['disentrain-pitch', 'disentrain-volume'])
#main('./', 'sandbox', '6', '6', ['disentrain-pitch'])
#main('./', 'sandbox', '7', '7', ['entrain-volume'])
#main('./', 'sandbox', '8', '8', ['disentrain-volume'])
#main('./', 'sandbox', '9', '9', [])
