// Single place to rename the app and point it at the backend.

export const APP_NAME = "Hidden Text Scanner";

// Backend URL.
// IMPORTANT: on a physical phone (Expo Go), "localhost" means the PHONE, not your computer.
// The URL must be your computer's LAN IP on the same Wi-Fi, e.g. "http://192.168.1.23:8000".
// Find it on macOS with:  ipconfig getifaddr en0
//
// Leave empty ("") to auto-detect: the app reuses the IP your phone already uses to reach
// the Expo dev server, which is normally your computer's LAN IP. Falls back to localhost on web.
export const BACKEND_URL_OVERRIDE: string = "";

export const BACKEND_PORT = 8000;
