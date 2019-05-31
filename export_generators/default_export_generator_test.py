# coding=utf-8
# Copyright 2019 The Tensor2Robot Authors.
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

"""Tests for tensor2robot.export_generators.default_export_generator."""

from __future__ import absolute_import
from __future__ import division

from __future__ import print_function

import numpy as np
from tensor2robot.export_generators import default_export_generator
from tensor2robot.preprocessors import noop_preprocessor
from tensor2robot.utils import mocks
import tensorflow as tf

MAX_STEPS = 4000
BATCH_SIZE = 32


class DefaultExportGeneratorTest(tf.test.TestCase):

  def _train_and_eval_reference_model(self, path):
    model_dir = self.create_tempdir().full_path
    mock_t2r_model = mocks.MockT2RModel(
        preprocessor_cls=noop_preprocessor.NoOpPreprocessor)

    # We create a tpu estimator for potential training.
    estimator = tf.contrib.tpu.TPUEstimator(
        model_fn=mock_t2r_model.model_fn,
        use_tpu=mock_t2r_model.is_device_tpu,
        config=tf.contrib.tpu.RunConfig(model_dir=model_dir),
        train_batch_size=BATCH_SIZE,
        eval_batch_size=BATCH_SIZE)

    mock_input_generator = mocks.MockInputGenerator(batch_size=BATCH_SIZE)
    mock_input_generator.set_specification_from_model(
        mock_t2r_model, tf.estimator.ModeKeys.TRAIN)

    # We optimize our network.
    estimator.train(
        input_fn=mock_input_generator.create_dataset_input_fn(
            mode=tf.estimator.ModeKeys.TRAIN),
        max_steps=MAX_STEPS)

    # Verify that the serving estimator does exactly the same as the normal
    # estimator with all the parameters.
    estimator_predict = tf.estimator.Estimator(
        model_fn=mock_t2r_model.model_fn,
        config=tf.estimator.RunConfig(model_dir=model_dir))

    prediction_ref = estimator_predict.predict(
        input_fn=mock_input_generator.create_dataset_input_fn(
            mode=tf.estimator.ModeKeys.EVAL))
    return model_dir, mock_t2r_model, prediction_ref

  def test_create_serving_input_receiver_numpy(self):
    (model_dir, mock_t2r_model,
     prediction_ref) = self._train_and_eval_reference_model('numpy')
    exporter = default_export_generator.DefaultExportGenerator()
    exporter.set_specification_from_model(mock_t2r_model)

    # Export trained serving estimator.
    estimator_exporter = tf.estimator.Estimator(
        model_fn=mock_t2r_model.model_fn,
        config=tf.estimator.RunConfig(model_dir=model_dir))

    serving_input_receiver_fn = (
        exporter.create_serving_input_receiver_numpy_fn())
    exported_savedmodel_path = estimator_exporter.export_saved_model(
        export_dir_base=model_dir,
        serving_input_receiver_fn=serving_input_receiver_fn,
        checkpoint_path=tf.train.latest_checkpoint(model_dir))

    # Load trained and exported serving estimator, run prediction and assert
    # it is the same as before exporting.
    feed_predictor_fn = tf.contrib.predictor.from_saved_model(
        exported_savedmodel_path)
    mock_input_generator = mocks.MockInputGenerator(batch_size=BATCH_SIZE)
    features, labels = mock_input_generator.create_numpy_data()
    for pos, value in enumerate(prediction_ref):
      actual = feed_predictor_fn({'x': features[pos, :].reshape(
          1, -1)})['logit'].flatten()
      predicted = value['logit'].flatten()
      np.testing.assert_almost_equal(
          actual=actual, desired=predicted, decimal=4)
      if labels[pos] > 0:
        self.assertGreater(predicted[0], 0)
      else:
        self.assertLess(predicted[0], 0)

  def test_create_serving_input_receiver_tf_example(self):
    (model_dir, mock_t2r_model,
     prediction_ref) = self._train_and_eval_reference_model('tf_example')

    # Now we can actually export our serving estimator.
    estimator_exporter = tf.estimator.Estimator(
        model_fn=mock_t2r_model.model_fn,
        config=tf.estimator.RunConfig(model_dir=model_dir))

    exporter = default_export_generator.DefaultExportGenerator()
    exporter.set_specification_from_model(mock_t2r_model)
    serving_input_receiver_fn = (
        exporter.create_serving_input_receiver_tf_example_fn())
    exported_savedmodel_path = estimator_exporter.export_saved_model(
        export_dir_base=model_dir,
        serving_input_receiver_fn=serving_input_receiver_fn,
        checkpoint_path=tf.train.latest_checkpoint(model_dir))

    # Now we can load our exported estimator graph, there are no dependencies
    # on the model_fn or preprocessor anymore.
    feed_predictor_fn = tf.contrib.predictor.from_saved_model(
        exported_savedmodel_path)
    mock_input_generator = mocks.MockInputGenerator(batch_size=BATCH_SIZE)
    features, labels = mock_input_generator.create_numpy_data()
    for pos, value in enumerate(prediction_ref):
      # We have to create our serialized tf.Example proto.
      example = tf.train.Example()
      example.features.feature['measured_position'].float_list.value.extend(
          features[pos])
      feed_dict = {
          'input_example_tensor':
              np.array(example.SerializeToString()).reshape(1,)
      }
      actual = feed_predictor_fn(feed_dict)['logit'].flatten()
      predicted = value['logit'].flatten()
      np.testing.assert_almost_equal(
          actual=actual, desired=predicted, decimal=4)
      if labels[pos] > 0:
        self.assertGreater(predicted[0], 0)
      else:
        self.assertLess(predicted[0], 0)

if __name__ == '__main__':
  tf.test.main()