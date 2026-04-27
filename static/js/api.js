/**
 * API Module
 * Handles all API calls to backend
 */

const buildHttpError = async (response) => {
  const err = new Error(`HTTP ${response.status}`);
  err.status = response.status;
  try {
    err.data = await response.json();
  } catch (_e) {
    err.data = null;
  }
  return err;
};

const buildSubmitBody = async (payload) => {
  const jsonText = JSON.stringify(payload || {});

  // For tiny payloads, compression overhead can outweigh gains.
  if (jsonText.length < 4096 || typeof CompressionStream === 'undefined') {
    return {
      body: jsonText,
      headers: {
        'Content-Type': 'application/json',
      },
    };
  }

  try {
    const encoder = new TextEncoder();
    const compressedStream = new CompressionStream('gzip');
    const writer = compressedStream.writable.getWriter();
    await writer.write(encoder.encode(jsonText));
    await writer.close();

    const compressedBuffer = await new Response(compressedStream.readable).arrayBuffer();
    return {
      body: compressedBuffer,
      headers: {
        'Content-Type': 'application/json',
        'Content-Encoding': 'gzip',
      },
    };
  } catch (_e) {
    return {
      body: jsonText,
      headers: {
        'Content-Type': 'application/json',
      },
    };
  }
};

// Helper: wrap a fetch with an AbortController timeout.
// If the fetch doesn't resolve within `ms` milliseconds the signal is aborted
// and the resulting AbortError is re-thrown as a TypeError (network error) so
// callers don't need special-case handling.
const fetchWithTimeout = (url, options, ms) => {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), ms);
  return fetch(url, { ...options, signal: controller.signal })
    .then(res => { clearTimeout(id); return res; })
    .catch(err => {
      clearTimeout(id);
      if (err.name === 'AbortError') throw new TypeError(`Request timed out after ${ms}ms: ${url}`);
      throw err;
    });
};

const API = {
  // Fetch attempt details with all answers
  getAttempt: async (attemptId) => {
    try {
      const response = await fetchWithTimeout(`${API_BASE}/attempts/${attemptId}/`, {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('authToken') || ''}`,
          'Content-Type': 'application/json',
        },
        credentials: 'same-origin',
      }, 8000); // 8 second timeout
      if (!response.ok) throw await buildHttpError(response);
      return await response.json();
    } catch (error) {
      console.error('Error fetching attempt:', error);
      throw error;
    }
  },

  // Save/update an answer
  saveAnswer: async (attemptId, payload) => {
    try {
      const response = await fetch(`${API_BASE}/attempts/${attemptId}/save_answer/`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('authToken') || ''}`,
          'Content-Type': 'application/json',
          'X-CSRFToken': CSRF_TOKEN,
        },
        body: JSON.stringify(payload),
        credentials: 'same-origin',
      });
      if (!response.ok) throw await buildHttpError(response);
      return await response.json();
    } catch (error) {
      console.error('Error saving answer:', error);
      throw error;
    }
  },

  // Check timing
  checkTiming: async (attemptId) => {
    try {
      const response = await fetch(`${API_BASE}/attempts/${attemptId}/check_timing/`, {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('authToken') || ''}`,
          'Content-Type': 'application/json',
        },
        credentials: 'same-origin',
      });
      if (!response.ok) throw await buildHttpError(response);
      return await response.json();
    } catch (error) {
      console.error('Error checking timing:', error);
      throw error;
    }
  },

  // Submit attempt
  submitAttempt: async (attemptId, payload = {}) => {
    try {
      const prepared = await buildSubmitBody(payload);
      const response = await fetchWithTimeout(`${API_BASE}/attempts/${attemptId}/submit/`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('authToken') || ''}`,
          'X-CSRFToken': CSRF_TOKEN,
          ...prepared.headers,
        },
        body: prepared.body,
        credentials: 'same-origin',
      }, 30000); // 30 second timeout — long enough for slow networks
      if (!response.ok) throw await buildHttpError(response);
      return await response.json();
    } catch (error) {
      console.error('Error submitting attempt:', error);
      throw error;
    }
  },

  // Get test details
  getTest: async (testId) => {
    try {
      const response = await fetch(`${API_BASE}/tests/${testId}/`, {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('authToken') || ''}`,
          'Content-Type': 'application/json',
        },
        credentials: 'same-origin',
      });
      if (!response.ok) throw await buildHttpError(response);
      return await response.json();
    } catch (error) {
      console.error('Error fetching test:', error);
      throw error;
    }
  },

  // Track time spent on a question
  trackQuestionTime: async (attemptId, questionId, timeSpentSeconds) => {    try {
      const response = await fetch(`${API_BASE}/attempts/${attemptId}/track_question_time/`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('authToken') || ''}`,
          'Content-Type': 'application/json',
          'X-CSRFToken': CSRF_TOKEN,
        },
        body: JSON.stringify({
          question: questionId,
          time_spent_seconds: timeSpentSeconds,
        }),
        credentials: 'same-origin',
      });
      if (!response.ok) throw await buildHttpError(response);
      return await response.json();
    } catch (error) {
      console.error('Error tracking question time:', error);
      throw error;
    }
  },

  // Save current timer remaining seconds (heartbeat for resume support)
  saveTimer: async (attemptId, remainingSeconds) => {
    try {
      await fetch(`${API_BASE}/attempts/${attemptId}/save_timer/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': CSRF_TOKEN,
        },
        body: JSON.stringify({ remaining_seconds: remainingSeconds }),
        credentials: 'same-origin',
        keepalive: true,
      });
    } catch (error) {
      console.warn('Timer heartbeat failed:', error);
    }
  },

  // Save timer via sendBeacon (guaranteed delivery on page unload)
  saveTimerBeacon: (attemptId, remainingSeconds) => {
    if (!navigator.sendBeacon) return;
    const blob = new Blob(
      [JSON.stringify({ remaining_seconds: remainingSeconds })],
      { type: 'application/json' }
    );
    navigator.sendBeacon(`${API_BASE}/attempts/${attemptId}/save_timer/`, blob);
  },
};
