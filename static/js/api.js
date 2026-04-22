/**
 * API Module
 * Handles all API calls to backend
 */

const API = {
  // Fetch attempt details with all answers
  getAttempt: async (attemptId) => {
    try {
      const response = await fetch(`${API_BASE}/attempts/${attemptId}/`, {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('authToken') || ''}`,
          'Content-Type': 'application/json',
        },
        credentials: 'same-origin',
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
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
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
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
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json();
    } catch (error) {
      console.error('Error checking timing:', error);
      throw error;
    }
  },

  // Submit attempt
  submitAttempt: async (attemptId, payload = {}) => {
    try {
      const response = await fetch(`${API_BASE}/attempts/${attemptId}/submit/`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('authToken') || ''}`,
          'Content-Type': 'application/json',
          'X-CSRFToken': CSRF_TOKEN,
        },
        body: JSON.stringify(payload),
        credentials: 'same-origin',
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
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
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
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
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
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
