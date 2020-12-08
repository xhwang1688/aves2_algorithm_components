# coding=utf-8
# Copyright 2018 The Google AI Language Team Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.



import os
import six
import codecs
import random
import collections
import tensorflow as tf
import PlatformNlp.tokenization as tokenization
from PlatformNlp.data.base_dataset import BaseDataset
from PlatformNlp.data import register_dataset


class InputExample(object):
    """A single training/test example for simple sequence classification."""

    def __init__(self, guid, text_a, text_b, label=None):
        """Constructs a InputExample.

        Args:
          guid: Unique id for the example.
          text_a: string. The untokenized text of the first sequence. For single
            sequence tasks, only this sequence must be specified.
          label: (Optional) string. The label of the example. This should be
            specified for train and dev examples, but not for test examples.
        """
        self.guid = guid
        self.text_a = text_a
        self.text_b = text_b
        self.label = label


class PaddingInputExample(object):
    """Fake example so the num input examples is a multiple of the batch size.

    When running eval/predict on the TPU, we need to pad the number of examples
    to be a multiple of the batch size, because the TPU requires a fixed batch
    size. The alternative is to drop the last batch, which is bad because it means
    the entire output data won't be generated.

    We use this class instead of `None` because treating `None` as padding
    battches could cause silent errors.
    """


class InputFeatures(object):
    """A single set of features of data."""

    def __init__(self,
                 input_ids_1,
                 input_ids_2,
                 label_id,
                 input_mask,
                 segment_ids,
                 is_real_example=True):
        self.input_ids_1 = input_ids_1
        self.input_ids_2 = input_ids_2
        self.label_id = label_id
        self.input_mask = input_mask
        self.segment_ids = segment_ids
        self.is_real_example = is_real_example


@register_dataset("text_similarity")
class TextSemilarityFixLenDataset(BaseDataset):
    """Loader for text semilarity Dataset"""
    def __init__(self, args):
        self.args = args
        self.max_seq_length = 200 if not args.max_seq_length or args.max_seq_length <= 0 else args.max_seq_length
        if int(self.max_seq_length) % 2 != 0:
            self.max_seq_length = self.max_seq_length + 1

        if args.label_file is not None and os.path.exists(args.label_file):
            self.label_mapping = {}
        else:
            self.label_mapping = six.moves.cPickle.load(open(args.label_file, 'rb'))

    def build_dataset(self, args, tokenizer):
        set_type = args.type
        data_file = args.data_file
        label_file = args.label_file
        output_file = args.output_file
        if not os.path.exists(data_file):
            raise FileExistsError("{} does not exists!!!".format(data_file))
        if os.path.exists(output_file):
            os.remove(output_file)
        all_lines = []
        with codecs.open(data_file, "r", 'utf-8', errors='ignore') as f:
            lines = []
            for line in f:
                line = line.strip('\n')
                line = line.strip("\r")
                line = line.split(',')
                if len(line) < 3:
                    continue
                lines.append(line)
            shuffle_index = list(range(len(lines)))
            random.shuffle(shuffle_index)
            for i in range(len(lines)):
                shuffle_i = shuffle_index[i]
                if len(lines[i]) != 3:
                    continue
                line_i = [str(lines[shuffle_i][0]), str(lines[shuffle_i][1]),  str(lines[shuffle_i][2])]
                all_lines.append(line_i)
            del lines

        examples = []
        for (i, line) in enumerate(all_lines):
            # Only the test set has a header
            guid = "%s-%s" % (set_type, i)
            text_a = tokenization.convert_to_unicode(line[0])
            text_b = tokenization.convert_to_unicode(line[1])
            label = tokenization.convert_to_unicode(line[2])
            if set_type.lower() == "train":
                if label not in self.label_mapping:
                    self.label_mapping[label] = len(self.label_mapping)
            examples.append(InputExample(guid=guid, text_a=text_a, text_b=text_b, label=label))

        if set_type.lower() != "train":
            if not os.path.exists(label_file):
                raise EnvironmentError("no labels exists !!!!!")
            self.label_mapping = six.moves.cPickle.load(open(label_file, 'rb'))
        else:
            with open(label_file, 'wb') as f:
                six.moves.cPickle.dump(self.label_mapping, f)

        writer = tf.python_io.TFRecordWriter(output_file)
        for (ex_index, example) in enumerate(examples):
            if ex_index % 10000 == 0:
                tf.logging.info("Writing example %d of %d" % (ex_index, len(examples)))

            feature = self.convert_single_example(ex_index, example, self.label_mapping, tokenizer)

            def create_int_feature(values):
                f = tf.train.Feature(int64_list=tf.train.Int64List(value=list(values)))
                return f

            def create_str_feature(value):
                if isinstance(value, str):
                    value = bytes(value, encoding='utf-8')
                f = tf.train.Feature(bytes_list=tf.train.BytesList(value=[value]))
                return f

            features = collections.OrderedDict()
            features["input_ids_1"] = create_int_feature(feature.input_ids_1)
            features["input_ids_2"] = create_int_feature(feature.input_ids_2)
            features["input_mask"] = create_int_feature(feature.input_mask)
            features["segment_ids"] = create_int_feature(feature.segment_ids)
            features["label_ids"] = create_int_feature([feature.label_id])
            features["is_real_example"] = create_int_feature(
                [int(feature.is_real_example)])

            tf_example = tf.train.Example(features=tf.train.Features(feature=features))
            writer.write(tf_example.SerializeToString())
        writer.close()

    def builder(self, tfrecord_file, is_training, batch_size, drop_remainder, args):
        name_to_features = {
            "input_ids_1": tf.FixedLenFeature([self.max_seq_length], tf.int64),
            "input_ids_2": tf.FixedLenFeature([self.max_seq_length], tf.int64),
            "input_mask": tf.FixedLenFeature([self.max_seq_length], tf.int64),
            "segment_ids": tf.FixedLenFeature([self.max_seq_length], tf.int64),
            "label_ids": tf.FixedLenFeature([], tf.int64),
            "is_real_example": tf.FixedLenFeature([], tf.int64),
        }
        args.name_to_features = name_to_features
        def _decode_record(record, name_to_features):
            """Decodes a record to a TensorFlow example."""
            example = tf.parse_single_example(record, name_to_features)

            # tf.Example only supports tf.int64, but the TPU only supports tf.int32.
            # So cast all int64 to int32.
            for name in list(example.keys()):
                t = example[name]
                if t.dtype == tf.int64:
                    t = tf.to_int32(t)
                example[name] = t

            return example

        def input_fn(params):
            """The actual input function."""
            # batch_size = params["batch_size"]

            # For training, we want a lot of parallel reading and shuffling.
            # For eval, we want no shuffling and parallel reading doesn't matter.
            d = tf.data.TFRecordDataset(tfrecord_file)
            if is_training:
                d = d.repeat()
                d = d.shuffle(buffer_size=100)

            d = d.apply(
                tf.contrib.data.map_and_batch(
                    lambda record: _decode_record(record, name_to_features),
                    batch_size=batch_size,
                    drop_remainder=drop_remainder))

            return d

        return input_fn

    def convert_single_example(self, ex_index, example, label_mapping, tokenizer):
        """Converts a single `InputExample` into a single `InputFeatures`."""

        if isinstance(example, PaddingInputExample):
            return InputFeatures(
                input_ids_1=[0] * (self.max_seq_length / 2),
                input_ids_2=[0] * (self.max_seq_length / 2),
                input_mask=[0] * self.max_seq_length,
                segment_ids=[0] * self.max_seq_length,
                label_id=0,
                is_real_example=False)

        tokens_a = []
        tokens_b = []
        segment_ids = []

        tokens_a.append("[CLS]")
        segment_ids.append(0)
        for token in example.tokens_a:
            tokens_a.append(token)
            segment_ids.append(0)
        tokens_a.append("[SEP]")
        segment_ids.append(0)

        input_ids_1 = tokenizer.convert_tokens_to_ids(tokens_a)
        # The mask has 1 for real tokens and 0 for padding tokens. Only real
        # tokens are attended to.
        input_mask = [1] * len(tokens_a)

        while len(input_ids_1) < (self.max_seq_length / 2):
            input_ids_1.append(0)
            input_mask.append(0)
            segment_ids.append(0)

        if example.tokens_b:
            for token in example.tokens_b:
                tokens_b.append(token)
                input_mask.append(1)
                segment_ids.append(1)
            tokens_b.append("[SEP]")
            segment_ids.append(1)
            input_mask.append(1)

        input_ids_2 = tokenizer.convert_tokens_to_ids(tokens_b)
        while len(input_ids_2) < (self.max_seq_length / 2):
            input_ids_2.append(0)
            input_mask.append(0)
            segment_ids.append(0)

        assert len(input_ids_1) == (self.max_seq_length / 2)
        assert len(input_ids_2) == (self.max_seq_length / 2)
        assert len(input_mask) == self.max_seq_length
        assert len(segment_ids) == self.max_seq_length

        label_id = 0
        if example.label != 'nan':
            label_id = int(label_mapping.get(example.label, 0))

        if ex_index < 5:
            tf.logging.info("*** Example ***")
            tf.logging.info("guid: %s" % (example.guid))
            tf.logging.info("tokens_a: %s" % " ".join(
                [tokenization.printable_text(x) for x in tokens_a]))
            tf.logging.info("tokens_b: %s" % " ".join(
                [tokenization.printable_text(x) for x in tokens_b]))
            tf.logging.info("input_ids_1: %s" % " ".join([str(x) for x in input_ids_1]))
            tf.logging.info("input_ids_2: %s" % " ".join([str(x) for x in input_ids_2]))
            tf.logging.info("input_mask: %s" % " ".join([str(x) for x in input_mask]))
            tf.logging.info("segment_ids: %s" % " ".join([str(x) for x in segment_ids]))
            tf.logging.info("label: %s (id = %d)" % (example.label, label_id))

        feature = InputFeatures(
            input_ids_1=input_ids_1,
            input_ids_2=input_ids_2,
            input_mask=input_mask,
            segment_ids=segment_ids,
            label_id=label_id,
            is_real_example=True)
        return feature