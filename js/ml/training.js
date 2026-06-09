/**
 * js/ml/training.js
 * In-browser training pipeline for the LSTM prediction model.
 *
 * Runs entirely in the browser using TensorFlow.js.
 * Training is triggered when fresh historical data is available and
 * when the user's device is idle (requestIdleCallback).
 *
 * Features:
 *  - Full training loop with dual-head output (classification + regression)
 *  - Progress callbacks (loss, epoch, totalEpochs)
 *  - Model saved after each epoch (default + best slots)
 *  - Early stopping based on val_loss patience
 *  - Background training via requestIdleCallback
 */

import { buildModel, saveModel, loadModel, MODEL_CONFIG } from './model.js';
import { buildFeatureMatrix, createWindows } from './preprocessing.js';

/**
 * @typedef {Object} TrainingProgress
 * @property {number} epoch
 * @property {number} totalEpochs
 * @property {number} loss
 * @property {number} valLoss
 */

/**
 * Train (or fine-tune) the model on a set of historical OHLCV candles.
 *
 * @param {import('./preprocessing.js').OHLCV[]} candles  - Historical data, oldest → newest
 * @param {(progress: TrainingProgress) => void} [onProgress]  - Progress callback
 * @returns {Promise<tf.LayersModel>}  The trained model
 */
export async function trainModel(candles, onProgress) {
  if (typeof tf === 'undefined') {
    throw new Error('TensorFlow.js is not loaded. Cannot train.');
  }

  console.log(`[Training] Starting with ${candles.length} candles…`);

  // 1. Build feature matrix
  const { features, priceMin, priceMax } = buildFeatureMatrix(candles);

  if (features.length < MODEL_CONFIG.inputWindowSize + 10) {
    throw new Error(`Not enough data for training. Need at least ${MODEL_CONFIG.inputWindowSize + 10} valid feature rows, got ${features.length}.`);
  }

  // 2. Create sliding windows (with regression labels for dual-head model)
  const { X, y, yReg } = createWindows(features, MODEL_CONFIG.inputWindowSize, priceMin, priceMax);

  if (X.length === 0) {
    throw new Error('No training windows could be created from the data.');
  }

  console.log(`[Training] Created ${X.length} training windows.`);

  // 3. Split into train/validation (80/20)
  const splitIdx = Math.floor(X.length * 0.8);
  const xTrain    = X.slice(0, splitIdx);
  const yTrain    = y.slice(0, splitIdx);
  const yRegTrain = yReg.slice(0, splitIdx);
  const xVal      = X.slice(splitIdx);
  const yVal      = y.slice(splitIdx);
  const yRegVal   = yReg.slice(splitIdx);

  // 4. Convert to tensors — dual-head model expects [cls_tensor, reg_tensor]
  const xTrainTensor    = tf.tensor3d(xTrain);
  const yTrainTensor    = tf.tensor2d(yTrain,    [yTrain.length, 1]);
  const yRegTrainTensor = tf.tensor2d(yRegTrain, [yRegTrain.length, 1]);
  const xValTensor      = tf.tensor3d(xVal);
  const yValTensor      = tf.tensor2d(yVal,    [yVal.length, 1]);
  const yRegValTensor   = tf.tensor2d(yRegVal, [yRegVal.length, 1]);

  // 5. Load existing model or build new one
  let model = await loadModel('default');
  if (!model) {
    console.log('[Training] No saved model found. Building new model.');
    model = buildModel();
  }

  // 6. Train with callbacks
  const totalEpochs = MODEL_CONFIG.epochs;
  let bestValLoss = Infinity;
  let patienceCounter = 0;
  const PATIENCE = MODEL_CONFIG.earlyStoppingPatience;

  await model.fit(xTrainTensor, [yTrainTensor, yRegTrainTensor], {
    epochs: totalEpochs,
    batchSize: MODEL_CONFIG.batchSize,
    validationData: [xValTensor, [yValTensor, yRegValTensor]],
    shuffle: true,
    callbacks: {
      onEpochEnd: async (epoch, logs) => {
        const progress = {
          epoch: epoch + 1,
          totalEpochs,
          loss: logs.loss,
          valLoss: logs.val_loss,
        };

        console.log(`[Training] Epoch ${progress.epoch}/${totalEpochs} — loss: ${logs.loss.toFixed(6)}, val_loss: ${logs.val_loss.toFixed(6)}`);

        if (onProgress) onProgress(progress);

        // Save after each epoch
        await saveModel(model, 'default');

        // Early stopping
        if (logs.val_loss < bestValLoss) {
          bestValLoss = logs.val_loss;
          patienceCounter = 0;
          await saveModel(model, 'best'); // save best separately
        } else {
          patienceCounter++;
          if (patienceCounter >= PATIENCE) {
            console.log(`[Training] Early stopping at epoch ${epoch + 1}. Best val_loss: ${bestValLoss.toFixed(6)}`);
            model.stopTraining = true;
          }
        }
      },
    },
  });

  // 7. Cleanup tensors
  xTrainTensor.dispose();
  yTrainTensor.dispose();
  yRegTrainTensor.dispose();
  xValTensor.dispose();
  yValTensor.dispose();
  yRegValTensor.dispose();

  // 8. Save scaling params for prediction-time descaling
  const scalingParams = { priceMin, priceMax };
  try {
    localStorage.setItem('nostradamus_scaling_params', JSON.stringify(scalingParams));
  } catch (e) {
    console.warn('[Training] Failed to save scaling params:', e.message);
  }

  console.log('[Training] Complete!');
  return model;
}

/**
 * Trigger a training run in the background using requestIdleCallback (if available).
 * Falls back to setTimeout on unsupported browsers.
 *
 * Returns a Promise that resolves to the trained model when training completes,
 * allowing callers to await completion and then record versioning info.
 *
 * @param {import('./preprocessing.js').OHLCV[]} candles
 * @param {(progress: TrainingProgress) => void} [onProgress]
 * @returns {Promise<tf.LayersModel>}
 */
export function scheduledTrain(candles, onProgress) {
  return new Promise((resolve, reject) => {
    const run = () => {
      trainModel(candles, onProgress).then(resolve).catch(err => {
        console.error('[Training] Background training failed:', err);
        reject(err);
      });
    };

    if (typeof requestIdleCallback === 'function') {
      requestIdleCallback(run, { timeout: 30000 });
    } else {
      setTimeout(run, 1000);
    }
  });
}
