# -*- coding: utf-8 -*-
"""
Created on Wed Nov 15 21:17:10 2017

@author: 100446517
"""

import os
import pickle
import numpy as np
from skimage import color
from utils import preproc


def unpickle(file):
    with open(file, 'rb') as fo:
        dict = pickle.load(fo, encoding='bytes')
    return dict


def read_cifar10_data(directory):
    names = unpickle('{}/batches.meta'.format(directory))[b'label_names']
    data, labels = [], []
    for i in range(1, 6):
        filename = '{}/data_batch_{}'.format(directory, i)
        batch_data = unpickle(filename)
        if len(data) > 0:
            data = np.vstack((data, batch_data[b'data']))
            labels = np.hstack((labels, batch_data[b'labels']))
        else:
            data = batch_data[b'data']
            labels = batch_data[b'labels']

    filename = '{}/test_batch'.format(directory)
    batch_data = unpickle(filename)
    data_test = batch_data[b'data']
    labels_test = batch_data[b'labels']

    return names, data, labels, data_test, labels_test


def load_cifar10_data(normalize=False, shuffle=False, flip=False, count=-1):
    names, data, labels, data_test, labels_test = read_cifar10_data('../../../datasets/cfar10/')

    if shuffle:
        np.random.shuffle(data)

    if count != -1:
        data = data[:count]

    return preproc(data, normalize=normalize, flip=flip)


def load_cfar10_test_data(normalize=False, count=-1):
    names, data, labels, data_test, labels_test = read_cifar10_data('../../../datasets/cfar10/')

    if count != -1:
        data_test = data[:count]

    return preproc(data_test, normalize=normalize)


def load_imagenet_data(idx, normalize=False, flip=False, count=-1):
    data_file = '../../../datasets/ImageNet/train_data_batch_'
    d = unpickle(data_file + str(idx))
    x = d['data']
    mean_image = d['mean']

    if count != -1:
        x = x[:count]

    return preproc(x, normalize=normalize, flip=flip, mean_image=mean_image)


def load_imagenet_test_data(normalize=False, count=-1):
    d = unpickle('../../../datasets/ImageNet/val_data')
    x = d['data']

    if count != -1:
        x = x[:count]

    return preproc(x, normalize=normalize)


def imagenet_data_generator(batch_size, normalize=False, flip=False, scale=1):
    while True:
        for idx in range(10, 0,-1):
            data_file = '../../../datasets/ImageNet/train_data_batch_'
            d = unpickle(data_file + str(idx))
            x = d['data']
            mean_image = d['mean']
            count = 0
            while count <= x.shape[0] - batch_size:
                data = x[count:count + batch_size]
                count = count + batch_size
                data_yuv, data_rgb = preproc(data, normalize=normalize, flip=flip, mean_image=mean_image)
                yield data_yuv[:, :, :, :1], data_yuv[:, :, :, 1:] * scale


def imagenet_test_data_generator(batch_size, normalize=False, scale=1, count=-1):
    d = unpickle('../../../datasets/ImageNet/val_data')
    x = d['data']

    if count != -1:
        x = x[:count]

    while True:
        count = 0
        while count <= x.shape[0] - batch_size:
            data = x[count:count + batch_size]
            count = count + batch_size
            data_yuv, data_rgb = preproc(data, normalize=normalize)
            yield data_yuv[:, :, :, :1], data_yuv[:, :, :, 1:] * scale