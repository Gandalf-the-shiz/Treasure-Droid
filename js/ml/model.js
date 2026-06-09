/**
 * js/ml/model.js
 * TensorFlow.js model definition for stock price direction prediction.
 *
 * Model overview:
 *  - Input: Sliding window of 30 days × 33 features
 *  - Architecture: Bidirectional LSTM (128) → Dropout(0.3) → LSTM(64) →
 *                  Dropout(0.2) → Dense(32, relu) → Dropout(0.2)
 *                  → cls_output: Dense(1, sigmoid)  — P(price UP tomorrow)
 *                  → reg_output: Dense(1, linear)   — predicted % return
 *  - Matches server-side train-model.py architecture exactly
 */

// ─── Hyperparameters ──────────────────────────────────────────
export const MODEL_CONFIG = {
  inputWindowSize: 30,      // Number of days of history fed as input
  featuresPerStep:  33,     // Features per time step — must match build-features.py FEATURE_COUNT
  lstmUnits:       [128, 64], // BiLSTM then LSTM layer sizes
  dropoutRate:     0.2,
  learningRate:    0.001,
  batchSize:       32,
  epochs:          50,
  earlyStoppingPatience: 5,  // stop if val_loss doesn't improve for this many epochs
};

/**
 * Build and return an untrained dual-head Bidirectional LSTM model matching the
 * server-side architecture in train-model.py.
 * Requires TensorFlow.js to be loaded (window.tf).
 *
 * @returns {tf.LayersModel}
 */
export function buildModel() {
  if (typeof tf === 'undefined') {
    throw new Error('TensorFlow.js is not loaded. Cannot build model.');
  }

  const input = tf.input({ shape: [MODEL_CONFIG.inputWindowSize, MODEL_CONFIG.featuresPerStep] });

  // Shared backbone
  let x = tf.layers.bidirectional({
    layer: tf.layers.lstm({ units: MODEL_CONFIG.lstmUnits[0], returnSequences: true }),
  }).apply(input);
  x = tf.layers.dropout({ rate: 0.3 }).apply(x);
  x = tf.layers.lstm({ units: MODEL_CONFIG.lstmUnits[1], returnSequences: false }).apply(x);
  x = tf.layers.dropout({ rate: MODEL_CONFIG.dropoutRate }).apply(x);
  x = tf.layers.dense({ units: 32, activation: 'relu' }).apply(x);
  x = tf.layers.dropout({ rate: MODEL_CONFIG.dropoutRate }).apply(x);

  // Classification head — P(UP) [0, 1]
  const clsOutput = tf.layers.dense({ units: 1, activation: 'sigmoid', name: 'cls_output' }).apply(x);

  // Regression head — predicted % return (linear activation)
  const regOutput = tf.layers.dense({ units: 1, activation: 'linear', name: 'reg_output' }).apply(x);

  const model = tf.model({ inputs: input, outputs: [clsOutput, regOutput] });

  model.compile({
    optimizer: tf.train.adam(MODEL_CONFIG.learningRate),
    loss: ['binaryCrossentropy', 'meanSquaredError'],
    lossWeights: [1.0, 0.5],
    metrics: { cls_output: 'accuracy' },
  });

  return model;
}


/**
 * Save model weights to localStorage.
 * @param {tf.LayersModel} model
 * @param {string} [slot='default']
 * @returns {Promise<void>}
 */
export async function saveModel(model, slot = 'default') {
  if (typeof tf === 'undefined') throw new Error('TensorFlow.js not loaded');
  const storageKey = `localstorage://nostradamus-model-${slot}`;
  await model.save(storageKey);
  console.log(`[Model] Saved to ${storageKey}`);
}

/**
 * Load the pre-trained V2 model from the repo (primary model).
 * @returns {Promise<tf.LayersModel|null>}
 */
export async function loadV2Model() {
  if (typeof tf === 'undefined') return null;
  try {
    const model = await tf.loadLayersModel('./models/v2/model.json');
    console.log('[Model] Loaded V2 model from repo');
    return model;
  } catch (err) {
    console.warn('[Model] Failed to load V2 model:', err.message);
    return null;
  }
}

/**
 * Load model weights.
 * Fallback chain: localStorage → V2 pre-trained → null (demo mode)
 *
 * @param {string} [slot='default']
 * @returns {Promise<tf.LayersModel|null>}  null if no model found anywhere
 */
export async function loadModel(slot = 'default') {
  if (typeof tf === 'undefined') return null;

  // 1. Try localStorage (user-trained model)
  const storageKey = `localstorage://nostradamus-model-${slot}`;
  try {
    const model = await tf.loadLayersModel(storageKey);
    console.log(`[Model] Loaded from ${storageKey}`);
    return model;
  } catch (err) {
    console.warn(`[Model] No saved model found in slot "${slot}":`, err.message);
  }

  // 2. Try V2 pre-trained model
  const v2 = await loadV2Model();
  if (v2) return v2;

  // 3. No model available — caller should fall back to demo mode
  console.warn('[Model] No model available. App will run in demo mode.');
  return null;
}
