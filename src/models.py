
from __future__ import print_function

import os
import time
import numpy as np
import tensorflow as tf

from tensorflow import keras
from abc import abstractmethod
from .networks import Generator, Discriminator, Baseline
from .dataset import Places365Dataset, Cifar10Dataset, BleachDataset
from .ops import pixelwise_accuracy, preprocess, postprocess
from .ops import COLORSPACE_RGB, COLORSPACE_LAB
from .utils import stitch_images, turing_test, imshow, visualize


class BaseModel:
    def __init__(self, sess, options):
        self.sess = sess
        self.options = options
        self.name = options.name
        self.samples_dir = os.path.join(options.checkpoints_path, 'samples')
        self.test_log_file  = os.path.join(options.checkpoints_path, 'log_%s.dat' % self.options.long_long_name)
        self.train_log_file = os.path.join(options.checkpoints_path, 'log_train_%s.dat' % self.options.long_name)
        self.dataset_test  = self.create_dataset(False)
        self.global_step   = tf.Variable(0, name='global_step', trainable=False)
        self.dataset_train = self.create_dataset(True) if options.mode == 0 else None
        self.sample_generator = self.dataset_test.generator(options.sample_size, True)
        self.epoch = 0
        self.iteration = 0
        self.is_built  = False

    def train(self):
        self.build()

        total = len(self.dataset_train)

        for epoch in range(self.options.epochs):
            lr_rate = self.sess.run(self.learning_rate)

            print('Training epoch: %d' % (epoch + 1) + " - learning rate: " + str(lr_rate))

            self.epoch = epoch + 1
            self.iteration = 0

            generator = self.dataset_train.generator(self.options.batch_size)
            progbar = keras.utils.Progbar(total, stateful_metrics=['epoch', 'iteration', 'step'])

            for input_rgb in generator:
                feed_dic = {self.input_rgb: input_rgb}

                self.iteration = self.iteration + 1
                self.sess.run([self.dis_train], feed_dict=feed_dic)
                self.sess.run([self.gen_train, self.accuracy], feed_dict=feed_dic)
                self.sess.run([self.gen_train, self.accuracy], feed_dict=feed_dic)

                lossD, lossD_fake, lossD_real, lossG, lossG_l1, lossG_gan, acc, step = self.eval_outputs(feed_dic=feed_dic)

                progbar.add(len(input_rgb), values=[
                    ("epoch", epoch + 1),
                    ("iteration", self.iteration),
                    ("step", step),
                    ("D loss", lossD),
                    ("D fake", lossD_fake),
                    ("D real", lossD_real),
                    ("G loss", lossG),
                    ("G L1", lossG_l1),
                    ("G gan", lossG_gan),
                    ("accuracy", acc)
                ])

                # log model at checkpoints
                if self.options.log and step % self.options.log_interval == 0:
                    with open(self.train_log_file, 'a') as f:
                        f.write('%d %d %f %f %f %f %f %f %f\n' % (self.epoch, step, lossD, lossD_fake, lossD_real, lossG, lossG_l1, lossG_gan, acc))

                    if self.options.visualize:
                        visualize(self.train_log_file, self.test_log_file, self.options.visualize_window, self.name)

                # sample model at checkpoints
                if self.options.sample and step % self.options.sample_interval == 0:
                    self.sample(show=False)

                # evaluate model at checkpoints
                if self.options.validate and self.options.validate_interval > 0 and step % self.options.validate_interval == 0:
                    self.evaluate()

                # save model at checkpoints
                if self.options.save and step % self.options.save_interval == 0:
                    self.save()

            if self.options.validate:
                self.evaluate()

    def evaluate(self):
        print('\n\nEvaluating epoch: %d' % self.epoch)
        test_total = len(self.dataset_test)
        test_generator = self.dataset_test.generator(self.options.batch_size)
        progbar = keras.utils.Progbar(test_total)

        result = []

        # if not self.options.evaluate_type and self.options.batch_size == 1:
        #     data_test_len = len(self.dataset_test)
        #     matrix = np.zeros((data_test_len, self.options.dimension, self.options.dimension, 3), dtype=np.uint8)
        #     scores, count = np.zeros((data_test_len), dtype=float), 0

        for input_rgb in test_generator:
            feed_dic = {self.input_rgb: input_rgb}

            self.sess.run([self.dis_loss, self.gen_loss, self.accuracy, ], feed_dict=feed_dic)

            # returns (D loss, D_fake loss, D_real loss, G loss, G_L1 loss, G_gan loss, accuracy, step)
            result.append(self.eval_outputs(feed_dic=feed_dic))

            progbar.add(len(input_rgb))

        #     if not self.options.evaluate_type and self.options.batch_size == 1:
        #         genval = self.gen.eval(feed_dict=feed_dic)
        #         matrix[count] = ((genval[0] + 1) * 127.5).astype(np.uint8)
        #         scores[count] = result[-1][6]
        #         count += 1

        # if not self.options.evaluate_type and self.options.batch_size == 1:
        #     sample = self.options.long_long_name + "_00000.data"
        #     with open(os.path.join(self.samples_dir, sample), 'wb') as f:
        #         np.save(f, {b'data': matrix, b'score': scores})

        result = np.mean(np.array(result), axis=0)
        print('Results: D loss: %f - D fake: %f - D real: %f - G loss: %f - G L1: %f - G gan: %f - accuracy: %f'
              % (result[0], result[1], result[2], result[3], result[4], result[5], result[6]))

        if self.options.log:
            with open(self.test_log_file, 'a') as f:
                # (epoch, step, lossD, lossD_fake, lossD_real, lossG, lossG_l1, lossG_gan, acc)
                f.write('%d %d %f %f %f %f %f %f %f\n' % (self.epoch, result[7], result[0], result[1], result[2], result[3], result[4], result[5], result[6]))

        # if not self.options.evaluate_type:
        #     self.sample(show=False)

        print('\n')

    def sample(self, show=True):
        self.build()

        input_rgb = next(self.sample_generator)
        feed_dic = {self.input_rgb: input_rgb}

        step, rate = self.sess.run([self.global_step, self.learning_rate])
        fake_image, input_gray = self.sess.run([self.sampler, self.input_gray], feed_dict=feed_dic)
        fake_image = postprocess(tf.convert_to_tensor(fake_image), colorspace_in=self.options.color_space, colorspace_out=COLORSPACE_RGB)
        img = stitch_images(input_gray, input_rgb, fake_image.eval())

        if not os.path.exists(self.samples_dir):
            os.makedirs(self.samples_dir)

        sample = self.options.long_long_name + "_" + str(step).zfill(5) + ".png"

        if show:
            imshow(np.array(img), self.name)
        else:
            print('\nsaving sample ' + sample + ' - learning rate: ' + str(rate))
            img.save(os.path.join(self.samples_dir, sample))

    def turing_test(self):
        batch_size = self.options.batch_size
        gen = self.dataset_test.generator(batch_size, True)
        count = 0
        score = 0

        while count < self.options.test_size:
            input_rgb = next(gen)
            feed_dic = {self.input_rgb: input_rgb}
            fake_image = self.sess.run(self.sampler, feed_dict=feed_dic)
            fake_image = postprocess(tf.convert_to_tensor(fake_image), colorspace_in=self.options.color_space, colorspace_out=COLORSPACE_RGB)

            for i in range(np.min([batch_size, self.options.test_size - count])):
                res = turing_test(input_rgb[i, :, :, :3], fake_image.eval()[i], self.options.test_delay)
                count += 1
                score += res
                print('success: %d - fail: %d - rate: %f' % (score, count - score, (count - score) / count))

    def build(self):
        if self.is_built:
            return

        self.is_built = True

        gen_factory = self.create_generator()
        dis_factory = self.create_discriminator()
        smoothing = 0.9 if self.options.label_smoothing else 1
        seed = seed = self.options.seed
        kernel = self.options.kernel_size

        self.input_rgb = tf.placeholder(tf.float32, shape=(None, None, None, 4), name='input_rgb')
        self.input_rgb_, self.input_gray = tf.split(self.input_rgb, [3, 1], 3)
        # self.input_gray = tf.image.rgb_to_grayscale(self.input_rgb)
        # self.input_gray = tf.image.rgb_to_grayscale(self.input_rgb)
        self.input_color = preprocess(self.input_rgb_, colorspace_in=COLORSPACE_RGB, colorspace_out=self.options.color_space)

        gen = gen_factory.create(self.input_gray, kernel, seed)
        # gen = self.gen
        # label, reall, fakel = [], [], []
        # shapes = tf.shape(self.input_gray)
        # rflen, stride = 128, tf.div(shapes[1], 4) # 64, 128 | 4, 8
        # for i in range(3): # 4, 3, 7
        #     pi = stride * i
        #     qi = pi + rflen
        #     for j in range(3): # 4, 3, 7
        #         pj = stride * j
        #         qj = pj + rflen
        #         label.append(self.input_gray [:, pi : qi, pj : qj, :])
        #         reall.append(self.input_color[:, pi : qi, pj : qj, :])
        #         fakel.append(gen[:, pi : qi, pj : qj :])
        # label = tf.concat(label, 0)
        # reall = tf.concat(reall, 0)
        # fakel = tf.concat(fakel, 0)
        # dis_real = dis_factory.create(tf.concat([label, reall], 3), kernel, seed)
        # dis_fake = dis_factory.create(tf.concat([label, fakel], 3), kernel, seed, reuse_variables=True)
        dis_real = dis_factory.create(tf.concat([self.input_gray, self.input_color], 3), kernel, seed)
        dis_fake = dis_factory.create(tf.concat([self.input_gray, gen], 3), kernel, seed, reuse_variables=True)

        gen_ce = tf.nn.sigmoid_cross_entropy_with_logits(logits=dis_fake, labels=tf.ones_like(dis_fake))
        dis_real_ce = tf.nn.sigmoid_cross_entropy_with_logits(logits=dis_real, labels=tf.ones_like(dis_real) * smoothing)
        dis_fake_ce = tf.nn.sigmoid_cross_entropy_with_logits(logits=dis_fake, labels=tf.zeros_like(dis_fake))

        self.dis_loss_real = tf.reduce_mean(dis_real_ce)
        self.dis_loss_fake = tf.reduce_mean(dis_fake_ce)
        self.dis_loss = tf.reduce_mean(dis_real_ce + dis_fake_ce)

        self.gen_loss_gan = tf.reduce_mean(gen_ce)
        self.gen_loss_l1 = tf.reduce_mean(tf.abs(self.input_color - gen)) * self.options.l1_weight
        self.gen_loss = self.gen_loss_gan + self.gen_loss_l1

        self.sampler = gen_factory.create(self.input_gray, kernel, seed, reuse_variables=True)
        self.accuracy = pixelwise_accuracy(self.input_color, gen, self.options.color_space, self.options.acc_thresh)
        self.learning_rate = tf.constant(self.options.lr)

        # learning rate decay
        if self.options.lr_decay_rate > 0:
            self.learning_rate = tf.maximum(1e-8, tf.train.exponential_decay(
                learning_rate=self.options.lr,
                global_step=self.global_step,
                decay_steps=self.options.lr_decay_steps,
                decay_rate=self.options.lr_decay_rate))

        # generator optimizaer
        self.gen_train = tf.train.AdamOptimizer(
            learning_rate=self.learning_rate,
            beta1=self.options.beta1
        ).minimize(self.gen_loss, var_list=gen_factory.var_list)

        # discriminator optimizaer
        self.dis_train = tf.train.AdamOptimizer(
            learning_rate=self.learning_rate,
            beta1=self.options.beta1
        ).minimize(self.dis_loss, var_list=dis_factory.var_list, global_step=self.global_step)

        self.saver = tf.train.Saver()

    def load(self):
        ckpt = tf.train.get_checkpoint_state(self.options.checkpoints_path)
        if ckpt is not None:
            print('loading model...\n')
            ckpt_name = os.path.basename(ckpt.model_checkpoint_path)
            self.saver.restore(self.sess, os.path.join(self.options.checkpoints_path, ckpt_name))
            return True

        return False

    def save(self):
        print('saving model...\n')
        self.saver.save(self.sess, os.path.join(self.options.checkpoints_path, 'CGAN_' + self.options.long_name), write_meta_graph=False)

    def eval_outputs(self, feed_dic):
        '''
        evaluates the loss and accuracy
        returns (D loss, D_fake loss, D_real loss, G loss, G_L1 loss, G_gan loss, accuracy, step)
        '''
        lossD_fake = self.dis_loss_fake.eval(feed_dict=feed_dic)
        lossD_real = self.dis_loss_real.eval(feed_dict=feed_dic)
        lossD = self.dis_loss.eval(feed_dict=feed_dic)

        lossG_l1 = self.gen_loss_l1.eval(feed_dict=feed_dic)
        lossG_gan = self.gen_loss_gan.eval(feed_dict=feed_dic)
        lossG = lossG_l1 + lossG_gan

        acc = self.accuracy.eval(feed_dict=feed_dic)
        step = self.sess.run(self.global_step)

        return lossD, lossD_fake, lossD_real, lossG, lossG_l1, lossG_gan, acc, step

    @abstractmethod
    def create_generator(self):
        raise NotImplementedError

    @abstractmethod
    def create_discriminator(self):
        raise NotImplementedError

    @abstractmethod
    def create_dataset(self, training):
        raise NotImplementedError


class Cifar10Model(BaseModel):
    def __init__(self, sess, options):
        super(Cifar10Model, self).__init__(sess, options)
        # if options.mode == 0:
        #     steps = int(np.ceil(len(self.dataset_train) / self.options.batch_size))
        #     self.options.save_interval *= steps
        #     self.options.sample_interval *= steps

    def create_generator(self):
        kernels_gen_encoder = [
            (64, 1, 0),     # [batch, 32, 32, ch] => [batch, 32, 32, 64]
            (128, 2, 0),    # [batch, 32, 32, 64] => [batch, 16, 16, 128]
            (256, 2, 0),    # [batch, 16, 16, 128] => [batch, 8, 8, 256]
            (512, 2, 0),    # [batch, 8, 8, 256] => [batch, 4, 4, 512]
            (512, 2, 0),    # [batch, 4, 4, 512] => [batch, 2, 2, 512]
        ]

        kernels_gen_decoder = [
            (512, 2, 0.5),  # [batch, 2, 2, 512] => [batch, 4, 4, 512]
            (256, 2, 0.5),  # [batch, 4, 4, 512] => [batch, 8, 8, 256]
            (128, 2, 0),    # [batch, 8, 8, 256] => [batch, 16, 16, 128]
            (64, 2, 0),     # [batch, 16, 16, 128] => [batch, 32, 32, 64]
        ]

        return Generator('gen', kernels_gen_encoder, kernels_gen_decoder)

    def create_discriminator(self):
        kernels_dis = [
            (64, 2, 0),     # [batch, 32, 32, ch] => [batch, 16, 16, 64]
            (128, 2, 0),    # [batch, 16, 16, 64] => [batch, 8, 8, 128]
            (256, 2, 0),    # [batch, 8, 8, 128] => [batch, 4, 4, 256]
            (512, 1, 0),    # [batch, 4, 4, 256] => [batch, 4, 4, 512]
        ]

        return Discriminator('dis', kernels_dis)

    def create_dataset(self, training=True):
        return Cifar10Dataset(
            path=self.options.dataset_path,
            dimension=self.options.dimension,
            training=training,
            evaluate=self.options.evaluate_type,
            augment=self.options.augment)



class Places365Model(BaseModel):
    def __init__(self, sess, options):
        super(Places365Model, self).__init__(sess, options)

    def create_generator(self):
        if self.options.dimension == 128:

            kernels_gen_encoder = [
                (64, 1, 0),     # [batch, 128, 128, ch] => [batch, 128, 128, 64]
                (64, 2, 0),     # [batch, 128, 128, 64] => [batch,  64,  64, 64]
                (128, 2, 0),    # [batch, 64, 64,  64] => [batch, 32, 32, 128]
                (256, 2, 0),    # [batch, 32, 32, 128] => [batch, 16, 16, 256]
                (512, 2, 0),    # [batch, 16, 16, 256] => [batch, 8, 8, 512]
                (512, 2, 0),    # [batch, 8, 8, 512] => [batch, 4, 4, 512]
                (512, 2, 0)     # [batch, 4, 4, 512] => [batch, 2, 2, 512]
            ]

            kernels_gen_decoder = [
                (512, 2, 0.5),  # [batch, 2, 2, 512] => [batch, 4, 4, 512]
                (512, 2, 0.5),  # [batch, 4, 4, 512] => [batch, 8, 8, 512]
                (256, 2, 0),    # [batch, 8, 8, 512] => [batch, 16, 16, 256]
                (128, 2, 0),    # [batch, 16, 16, 256] => [batch, 32, 32, 128]
                (64, 2, 0),     # [batch, 32, 32, 128] => [batch, 64, 64,  64]
                (64, 2, 0),     # [batch, 64, 64, 128] => [batch, 128, 128, 64]
            ]

        elif self.options.dimension == 256:

            kernels_gen_encoder = [
                (64, 1, 0),     # [batch, 256, 256, ch] => [batch, 256, 256, 64]
                (64, 2, 0),     # [batch, 256, 256, 64] => [batch, 128, 128, 64]
                (128, 2, 0),    # [batch, 128, 128, 64] => [batch, 64, 64, 128]
                (256, 2, 0),    # [batch, 64, 64, 128] => [batch, 32, 32, 256]
                (512, 2, 0),    # [batch, 32, 32, 256] => [batch, 16, 16, 512]
                (512, 2, 0),    # [batch, 16, 16, 512] => [batch, 8, 8, 512]
                (512, 2, 0),    # [batch, 8, 8, 512] => [batch, 4, 4, 512]
                (512, 2, 0)     # [batch, 4, 4, 512] => [batch, 2, 2, 512]
            ]

            kernels_gen_decoder = [
                (512, 2, 0.5),  # [batch, 2, 2, 512] => [batch, 4, 4, 512]
                (512, 2, 0.5),  # [batch, 4, 4, 512] => [batch, 8, 8, 512]
                (512, 2, 0.5),  # [batch, 8, 8, 512] => [batch, 16, 16, 512]
                (256, 2, 0),    # [batch, 16, 16, 512] => [batch, 32, 32, 256]
                (128, 2, 0),    # [batch, 32, 32, 256] => [batch, 64, 64, 128]
                (64, 2, 0),     # [batch, 64, 64, 128] => [batch, 128, 128, 64]
                (64, 2, 0)      # [batch, 128, 128, 64] => [batch, 256, 256, 64]
            ]

        return Generator('gen', kernels_gen_encoder, kernels_gen_decoder)

    def create_discriminator(self):
        if self.options.dimension == 128:

            kernels_dis = [
                (64, 2, 0),     # [batch, 128, 128, ch] => [batch, 64, 64,  64]
                (128, 2, 0),    # [batch,  64,  64, 64] => [batch, 32, 32, 128]
                (256, 2, 0),    # [batch, 32, 32, 128] => [batch, 16, 16, 256]
                (512, 2, 0),    # [batch, 16, 16, 256] => [batch,  8,  8, 512]
                (512, 2, 0),    # [batch,  8,  8, 512] => [batch,  4,  4, 512]
                (512, 1, 0),    # [batch, 4, 4, 512] => [batch, 4, 4, 512]
            ]

        elif self.self.options.dimension == 256:

            kernels_dis = [
                (64, 2, 0),     # [batch, 256, 256, ch] => [batch, 128, 128, 64]
                (128, 2, 0),    # [batch, 128, 128, 64] => [batch, 64, 64, 128]
                (256, 2, 0),    # [batch, 64, 64, 128] => [batch, 32, 32, 256]
                (512, 2, 0),    # [batch, 32, 32, 256] => [batch, 16, 16, 512]
                (512, 2, 0),    # [batch, 16, 16, 512] => [batch, 8, 8, 512]
                (512, 2, 0),    # [batch, 8, 8, 512] => [batch, 4, 4, 512]
                (512, 1, 0),    # [batch, 4, 4, 512] => [batch, 4, 4, 512]
            ]

        return Discriminator('dis', kernels_dis)

    def create_dataset(self, training=True):
        return Places365Dataset(
            path=self.options.dataset_path,
            dimension=self.options.dimension,
            training=training,
            evaluate=self.options.evaluate_type,
            augment=self.options.augment)



# Definition of the new Model classes

class BleachModel(BaseModel):
    def __init__(self, sess, options):
        super(BleachModel, self).__init__(sess, options)
        if options.mode == 0:
            steps = int(np.ceil(len(self.dataset_train) / self.options.batch_size))
            self.options.save_interval *= steps
            self.options.sample_interval *= steps

    def create_generator(self):
        if self.options.dimension == 128:

            kernels_gen_encoder = [
                (64, 1, 0),     # [batch, 128, 128, ch] => [batch, 128, 128, 64]
                (64, 2, 0),     # [batch, 128, 128, 64] => [batch,  64,  64, 64]
                (128, 2, 0),    # [batch, 64, 64,  64] => [batch, 32, 32, 128]
                (256, 2, 0),    # [batch, 32, 32, 128] => [batch, 16, 16, 256]
                (512, 2, 0),    # [batch, 16, 16, 256] => [batch, 8, 8, 512]
                (512, 2, 0),    # [batch, 8, 8, 512] => [batch, 4, 4, 512]
                (512, 2, 0)     # [batch, 4, 4, 512] => [batch, 2, 2, 512]
            ]

            kernels_gen_decoder = [
                (512, 2, 0.5),  # [batch, 2, 2, 512] => [batch, 4, 4, 512]
                (512, 2, 0.5),  # [batch, 4, 4, 512] => [batch, 8, 8, 512]
                (256, 2, 0),    # [batch, 8, 8, 512] => [batch, 16, 16, 256]
                (128, 2, 0),    # [batch, 16, 16, 256] => [batch, 32, 32, 128]
                (64, 2, 0),     # [batch, 32, 32, 128] => [batch, 64, 64,  64]
                (64, 2, 0),     # [batch, 64, 64, 128] => [batch, 128, 128, 64]
            ]

        elif self.options.dimension == 256:

            kernels_gen_encoder = [
                (64, 1, 0),     # [batch, 256, 256, ch] => [batch, 256, 256, 64]
                (64, 2, 0),     # [batch, 256, 256, 64] => [batch, 128, 128, 64]
                (128, 2, 0),    # [batch, 128, 128, 64] => [batch, 64, 64, 128]
                (256, 2, 0),    # [batch, 64, 64, 128] => [batch, 32, 32, 256]
                (512, 2, 0),    # [batch, 32, 32, 256] => [batch, 16, 16, 512]
                (512, 2, 0),    # [batch, 16, 16, 512] => [batch, 8, 8, 512]
                (512, 2, 0),    # [batch, 8, 8, 512] => [batch, 4, 4, 512]
                (512, 2, 0)     # [batch, 4, 4, 512] => [batch, 2, 2, 512]
            ]

            kernels_gen_decoder = [
                (512, 2, 0.5),  # [batch, 2, 2, 512] => [batch, 4, 4, 512]
                (512, 2, 0.5),  # [batch, 4, 4, 512] => [batch, 8, 8, 512]
                (512, 2, 0.5),  # [batch, 8, 8, 512] => [batch, 16, 16, 512]
                (256, 2, 0),    # [batch, 16, 16, 512] => [batch, 32, 32, 256]
                (128, 2, 0),    # [batch, 32, 32, 256] => [batch, 64, 64, 128]
                (64, 2, 0),     # [batch, 64, 64, 128] => [batch, 128, 128, 64]
                (64, 2, 0)      # [batch, 128, 128, 64] => [batch, 256, 256, 64]
            ]

        return Generator('gen', kernels_gen_encoder, kernels_gen_decoder)

    def create_discriminator(self):
        if self.options.dimension == 128:

            kernels_dis = [
                (64, 2, 0),     # [batch, 128, 128, ch] => [batch, 64, 64,  64]
                (128, 2, 0),    # [batch,  64,  64, 64] => [batch, 32, 32, 128]
                (256, 2, 0),    # [batch, 32, 32, 128] => [batch, 16, 16, 256]
                (512, 2, 0),    # [batch, 16, 16, 256] => [batch,  8,  8, 512]
                (512, 2, 0),    # [batch,  8,  8, 512] => [batch,  4,  4, 512]
                (512, 1, 0),    # [batch, 4, 4, 512] => [batch, 4, 4, 512]
            ]

        elif self.options.dimension == 256:

            kernels_dis = [
                (64, 2, 0),     # [batch, 256, 256, ch] => [batch, 128, 128, 64]
                (128, 2, 0),    # [batch, 128, 128, 64] => [batch, 64, 64, 128]
                (256, 2, 0),    # [batch, 64, 64, 128] => [batch, 32, 32, 256]
                (512, 2, 0),    # [batch, 32, 32, 256] => [batch, 16, 16, 512]
                (512, 2, 0),    # [batch, 16, 16, 512] => [batch, 8, 8, 512] #
                (512, 2, 0),    # [batch, 8, 8, 512] => [batch, 4, 4, 512] #
                (512, 1, 0),    # [batch, 4, 4, 512] => [batch, 4, 4, 512]
            ]

        return Discriminator('dis', kernels_dis)

    def create_dataset(self, training=True):
        return BleachDataset(
            path=self.options.dataset_path,
            dimension=self.options.dimension,
            training=training,
            evaluate=self.options.evaluate_type,
            augment=self.options.augment)



# Start of the baseline model

class BaselineModel(BaseModel):
    def __init__(self, sess, options):
        super(BaselineModel, self).__init__(sess, options)
        if options.mode == 0:
            steps = int(np.ceil(len(self.dataset_train) / self.options.batch_size))
            self.options.save_interval *= steps
            self.options.sample_interval *= steps

    def create_generator(self):    
        if self.options.dimension == 128:
        
            kernels_gen_encoder = [
                (64, 1, 0),     # [batch, 128, 128, ch] => [batch, 128, 128, 64]
                (64, 2, 0),     # [batch, 128, 128, 64] => [batch,  64,  64, 64]
                (128, 2, 0),    # [batch, 64, 64,  64] => [batch, 32, 32, 128]
                (256, 2, 0),    # [batch, 32, 32, 128] => [batch, 16, 16, 256]
                (512, 2, 0),    # [batch, 16, 16, 256] => [batch, 8, 8, 512]
                (512, 2, 0),    # [batch, 8, 8, 512] => [batch, 4, 4, 512]
                (512, 2, 0)     # [batch, 4, 4, 512] => [batch, 2, 2, 512]
            ]

            kernels_gen_decoder = [
                (512, 2, 0.5),  # [batch, 2, 2, 512] => [batch, 4, 4, 512]
                (512, 2, 0.5),  # [batch, 4, 4, 512] => [batch, 8, 8, 512]
                (256, 2, 0),    # [batch, 8, 8, 512] => [batch, 16, 16, 256]
                (128, 2, 0),    # [batch, 16, 16, 256] => [batch, 32, 32, 128]
                (64, 2, 0),     # [batch, 32, 32, 128] => [batch, 64, 64,  64]
                (64, 2, 0),     # [batch, 64, 64, 128] => [batch, 128, 128, 64]
            ]

        elif self.options.dimension == 256:

            kernels_gen_encoder = [
                (64, 1, 0),     # [batch, 256, 256, ch] => [batch, 256, 256, 64]
                (64, 2, 0),     # [batch, 256, 256, 64] => [batch, 128, 128, 64]
                (128, 2, 0),    # [batch, 128, 128, 64] => [batch, 64, 64, 128]
                (256, 2, 0),    # [batch, 64, 64, 128] => [batch, 32, 32, 256]
                (512, 2, 0),    # [batch, 32, 32, 256] => [batch, 16, 16, 512]
                (512, 2, 0),    # [batch, 16, 16, 512] => [batch, 8, 8, 512]
                (512, 2, 0),    # [batch, 8, 8, 512] => [batch, 4, 4, 512]
                (512, 2, 0)     # [batch, 4, 4, 512] => [batch, 2, 2, 512]
            ]

            kernels_gen_decoder = [
                (512, 2, 0.5),  # [batch, 2, 2, 512] => [batch, 4, 4, 512]
                (512, 2, 0.5),  # [batch, 4, 4, 512] => [batch, 8, 8, 512]
                (512, 2, 0.5),  # [batch, 8, 8, 512] => [batch, 16, 16, 512]
                (256, 2, 0),    # [batch, 16, 16, 512] => [batch, 32, 32, 256]
                (128, 2, 0),    # [batch, 32, 32, 256] => [batch, 64, 64, 128]
                (64, 2, 0),     # [batch, 64, 64, 128] => [batch, 128, 128, 64]
                (64, 2, 0)      # [batch, 128, 128, 64] => [batch, 256, 256, 64]
            ]

        return Baseline('gen', kernels_gen_encoder, kernels_gen_decoder)

    def create_discriminator(self):
        return 0

    def create_dataset(self, training=True):
        return BleachDataset(
            path=self.options.dataset_path,
            dimension=self.options.dimension,
            training=training,
            evaluate=self.options.evaluate_type,
            augment=self.options.augment)

    def train(self):
        self.build()

        total = len(self.dataset_train)

        for epoch in range(self.options.epochs):
            lr_rate = self.sess.run(self.learning_rate)

            print('Training epoch: %d' % (epoch + 1) + " - learning rate: " + str(lr_rate))

            self.epoch = epoch + 1
            self.iteration = 0

            generator = self.dataset_train.generator(self.options.batch_size)
            progbar = keras.utils.Progbar(total, stateful_metrics=['epoch', 'iteration', 'step'])

            for input_rgb in generator:
                feed_dic = {self.input_rgb: input_rgb}

                self.iteration = self.iteration + 1
                self.sess.run([self.gen_train, self.accuracy], feed_dict=feed_dic)

                lossG, lossG_l1, acc, step = self.eval_outputs(feed_dic=feed_dic)

                progbar.add(len(input_rgb), values=[
                    ("epoch", epoch + 1),
                    ("iteration", self.iteration),
                    ("step", step),
                    ("G loss", lossG),
                    ("G L1", lossG_l1),
                    ("accuracy", acc)
                ])

                # log model at checkpoints
                if self.options.log and step % self.options.log_interval == 0:
                    with open(self.train_log_file, 'a') as f:
                        f.write('%d %d %f %f %f\n' % (self.epoch, step, lossG, lossG_l1, acc))

                    if self.options.visualize:
                        visualize(self.train_log_file, self.test_log_file, self.options.visualize_window, self.name)
                # print(self.options.sample_interval)
                # sample model at checkpoints
                if self.options.sample and step % self.options.sample_interval == 0:
                    # print('Inside saving sample')
                    self.sample(show=False)

                # evaluate model at checkpoints
                if self.options.validate and self.options.validate_interval > 0 and step % self.options.validate_interval == 0:
                    self.evaluate()

                # save model at checkpoints
                if self.options.save and step % self.options.save_interval == 0:
                    self.save()

            if self.options.validate:
                self.evaluate()

    def evaluate(self):
        print('\n\nEvaluating epoch: %d' % self.epoch)
        test_total = len(self.dataset_test)
        test_generator = self.dataset_test.generator(self.options.batch_size)
        progbar = keras.utils.Progbar(test_total)

        result = []

        for input_rgb in test_generator:
            feed_dic = {self.input_rgb: input_rgb}

            self.sess.run([self.gen_loss, self.accuracy], feed_dict=feed_dic)

            # returns (G loss, G_L1 loss, accuracy, step)
            result.append(self.eval_outputs(feed_dic=feed_dic))

            progbar.add(len(input_rgb))

        result = np.mean(np.array(result), axis=0)
        print('Results: G loss: %f - G L1: %f - accuracy: %f'
              % (result[0], result[1], result[2]))

        if self.options.log:
            with open(self.test_log_file, 'a') as f:
                # (epoch, step, lossG, lossG_l1, acc)
                f.write('%d %d %f %f %f \n' % (self.epoch, result[3], result[0], result[1], result[2]))

        # if not self.options.evaluate_type:
        #     self.sample(show=False)

        print('\n')

    def sample(self, show=True):
        self.build()

        input_rgb = next(self.sample_generator)
        feed_dic = {self.input_rgb: input_rgb}

        step, rate = self.sess.run([self.global_step, self.learning_rate])
        fake_image, input_gray = self.sess.run([self.sampler, self.input_gray], feed_dict=feed_dic)
        fake_image = postprocess(tf.convert_to_tensor(fake_image), colorspace_in=self.options.color_space, colorspace_out=COLORSPACE_RGB)
        img = stitch_images(input_gray, input_rgb, fake_image.eval())

        if not os.path.exists(self.samples_dir):
            os.makedirs(self.samples_dir)

        sample = self.options.long_long_name + "_" + str(step).zfill(5) + ".png"

        if show:
            imshow(np.array(img), self.name)
        else:
            print('\nsaving sample ' + sample + ' - learning rate: ' + str(rate))
            img.save(os.path.join(self.samples_dir, sample))

    def turing_test(self):
        batch_size = self.options.batch_size
        gen = self.dataset_test.generator(batch_size, True)
        count = 0
        score = 0

        while count < self.options.test_size:
            input_rgb = next(gen)
            feed_dic = {self.input_rgb: input_rgb}
            fake_image = self.sess.run(self.sampler, feed_dict=feed_dic)
            fake_image = postprocess(tf.convert_to_tensor(fake_image), colorspace_in=self.options.color_space, colorspace_out=COLORSPACE_RGB)

            for i in range(np.min([batch_size, self.options.test_size - count])):
                res = turing_test(input_rgb[i], fake_image.eval()[i], self.options.test_delay)
                count += 1
                score += res
                print('success: %d - fail: %d - rate: %f' % (score, count - score, (count - score) / count))

    def build(self):
        if self.is_built:
            return

        self.is_built = True

        gen_factory = self.create_generator()
        smoothing = 0.9 if self.options.label_smoothing else 1
        seed = seed = self.options.seed
        kernel = self.options.kernel_size

        self.input_rgb = tf.placeholder(tf.float32, shape=(None, None, None, 4), name='input_rgb')
        self.input_rgb_, self.input_gray = tf.split(self.input_rgb, [3, 1], 3)
        # self.input_gray = tf.image.rgb_to_grayscale(self.input_rgb)
        # self.input_gray = tf.image.rgb_to_grayscale(self.input_rgb)
        self.input_color = preprocess(self.input_rgb_, colorspace_in=COLORSPACE_RGB, colorspace_out=self.options.color_space)

        gen = gen_factory.create(self.input_gray, kernel, seed)

        # Baseline loss (l1 loss)
        self.gen_loss_l1 = tf.reduce_mean(tf.abs(self.input_color - gen)) * self.options.l1_weight #
        self.gen_loss = self.gen_loss_l1

        self.sampler = gen_factory.create(self.input_gray, kernel, seed, reuse_variables=True)
        self.accuracy = pixelwise_accuracy(self.input_color, gen, self.options.color_space, self.options.acc_thresh)
        self.learning_rate = tf.constant(self.options.lr)

        # learning rate decay
        if self.options.lr_decay_rate > 0:
            self.learning_rate = tf.maximum(1e-8, tf.train.exponential_decay(
                learning_rate=self.options.lr,
                global_step=self.global_step,
                decay_steps=self.options.lr_decay_steps,
                decay_rate=self.options.lr_decay_rate))

        # generator optimizaer
        self.gen_train = tf.train.AdamOptimizer(
            learning_rate=self.learning_rate,
            beta1=self.options.beta1
        ).minimize(self.gen_loss, var_list=gen_factory.var_list, global_step=self.global_step)


        self.saver = tf.train.Saver()

    def load(self):
        ckpt = tf.train.get_checkpoint_state(self.options.checkpoints_path)
        if ckpt is not None:
            print('loading model...\n')
            ckpt_name = os.path.basename(ckpt.model_checkpoint_path)
            self.saver.restore(self.sess, os.path.join(self.options.checkpoints_path, ckpt_name))
            return True

        return False

    def save(self):
        print('saving model...\n')
        self.saver.save(self.sess, os.path.join(self.options.checkpoints_path, 'Baseline_' + self.options.long_name), write_meta_graph=False)

    def eval_outputs(self, feed_dic):
        '''
        evaluates the loss and accuracy
        returns (G loss, G_L1 loss, accuracy, step)
        '''

        lossG_l1 = self.gen_loss_l1.eval(feed_dict=feed_dic)
        lossG = lossG_l1

        acc = self.accuracy.eval(feed_dict=feed_dic)
        step = self.sess.run(self.global_step)

        return lossG, lossG_l1, acc, step