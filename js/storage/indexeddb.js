/**
 * js/storage/indexeddb.js
 * IndexedDB wrapper for storing large data that exceeds localStorage's 5 MB limit.
 *
 * Use cases:
 *  - Model weights (TF.js models can exceed 5 MB for the V2 BiLSTM)
 *  - Large historical OHLCV datasets
 *  - Feature matrix caches
 *
 * API:
 *  get(storeName, key)           → Promise<any>   — null if not found
 *  set(storeName, key, value)    → Promise<void>
 *  delete(storeName, key)        → Promise<void>
 *  clear(storeName)              → Promise<void>
 *  keys(storeName)               → Promise<string[]>
 *
 * All store names must be declared in STORE_NAMES below before use.
 * New stores can be added to STORE_NAMES — the DB version is bumped automatically.
 */

const DB_NAME    = 'NostradamusDB';
const DB_VERSION = 2;

/** All object store names used by the application. */
export const STORE_NAMES = {
  MODEL_WEIGHTS:  'modelWeights',   // TF.js model artifacts
  HISTORICAL_DATA:'historicalData', // OHLCV candle arrays per ticker
  FEATURE_CACHE:  'featureCache',   // Pre-computed feature matrices
  QUOTE_CACHE:    'quoteCache',     // Live quotes with short TTL
};

/** @type {IDBDatabase|null} */
let _db = null;

/**
 * Open (or reuse) the IndexedDB connection.
 * Creates all object stores declared in STORE_NAMES on first open or version upgrade.
 *
 * @returns {Promise<IDBDatabase>}
 */
function openDB() {
  if (_db) return Promise.resolve(_db);

  return new Promise((resolve, reject) => {
    if (typeof indexedDB === 'undefined') {
      reject(new Error('IndexedDB is not supported in this environment.'));
      return;
    }

    const request = indexedDB.open(DB_NAME, DB_VERSION);

    request.onupgradeneeded = (event) => {
      const db = event.target.result;
      for (const storeName of Object.values(STORE_NAMES)) {
        if (!db.objectStoreNames.contains(storeName)) {
          db.createObjectStore(storeName);
        }
      }
    };

    request.onsuccess = (event) => {
      _db = event.target.result;
      // Handle unexpected version changes (e.g., other tab upgrades)
      _db.onversionchange = () => {
        _db.close();
        _db = null;
      };
      resolve(_db);
    };

    request.onerror = (event) => {
      reject(new Error(`IndexedDB open failed: ${event.target.error?.message}`));
    };
  });
}

/**
 * Retrieve a value from IndexedDB.
 *
 * @param {string} storeName  - One of STORE_NAMES values
 * @param {string} key
 * @returns {Promise<any>}  The stored value, or null if not found
 */
export async function get(storeName, key) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx      = db.transaction(storeName, 'readonly');
    const store   = tx.objectStore(storeName);
    const request = store.get(key);

    request.onsuccess  = () => resolve(request.result ?? null);
    request.onerror    = () => reject(new Error(`IDB get failed: ${request.error?.message}`));
  });
}

/**
 * Store a value in IndexedDB.
 *
 * @param {string} storeName  - One of STORE_NAMES values
 * @param {string} key
 * @param {*} value           - Any structured-clonable value
 * @returns {Promise<void>}
 */
export async function set(storeName, key, value) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx      = db.transaction(storeName, 'readwrite');
    const store   = tx.objectStore(storeName);
    const request = store.put(value, key);

    request.onsuccess  = () => resolve();
    request.onerror    = () => reject(new Error(`IDB set failed: ${request.error?.message}`));
  });
}

/**
 * Delete a single entry from IndexedDB.
 *
 * @param {string} storeName
 * @param {string} key
 * @returns {Promise<void>}
 */
export async function deleteEntry(storeName, key) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx      = db.transaction(storeName, 'readwrite');
    const store   = tx.objectStore(storeName);
    const request = store.delete(key);

    request.onsuccess  = () => resolve();
    request.onerror    = () => reject(new Error(`IDB delete failed: ${request.error?.message}`));
  });
}

/**
 * Clear all entries in a given object store.
 *
 * @param {string} storeName
 * @returns {Promise<void>}
 */
export async function clear(storeName) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx      = db.transaction(storeName, 'readwrite');
    const store   = tx.objectStore(storeName);
    const request = store.clear();

    request.onsuccess  = () => resolve();
    request.onerror    = () => reject(new Error(`IDB clear failed: ${request.error?.message}`));
  });
}

/**
 * List all keys in a given object store.
 *
 * @param {string} storeName
 * @returns {Promise<string[]>}
 */
export async function keys(storeName) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx      = db.transaction(storeName, 'readonly');
    const store   = tx.objectStore(storeName);
    const request = store.getAllKeys();

    request.onsuccess  = () => resolve(request.result ?? []);
    request.onerror    = () => reject(new Error(`IDB keys failed: ${request.error?.message}`));
  });
}
