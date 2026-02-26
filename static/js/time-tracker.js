/**
 * Time Tracker Module
 * Tracks time spent viewing each question
 */

const TimeTracker = {
  currentlyViewingQuestionId: null,
  questionViewStartTime: null,
  attemptId: null,
  updateInterval: 5000, // Send time to server every 5 seconds
  pendingTimeUpdates: {}, // Track accumulated time: { questionId: seconds }
  intervalId: null,

  /**
   * Initialize time tracker
   * @param {number} attemptId - The attempt ID
   */
  init: (attemptId) => {
    console.log('TimeTracker.init() called with attemptId:', attemptId);
    TimeTracker.attemptId = attemptId;
    TimeTracker.startPeriodicSync();
    console.log('TimeTracker initialized successfully');
  },

  /**
   * Start tracking time on a question
   * Called when a question is selected/displayed
   * @param {number} questionId
   */
  startTracking: (questionId) => {
    // Save time for previously viewed question
    if (TimeTracker.currentlyViewingQuestionId !== null && TimeTracker.currentlyViewingQuestionId !== questionId) {
      TimeTracker.recordTimeForQuestion(TimeTracker.currentlyViewingQuestionId);
    }

    // Start tracking new question
    TimeTracker.currentlyViewingQuestionId = questionId;
    TimeTracker.questionViewStartTime = Date.now();
    console.log(`Started tracking question ${questionId} at ${new Date().toISOString()}`);
    
    // Extra safeguard: Ensure tracking is actually set (fixes race condition edge cases)
    if (TimeTracker.questionViewStartTime === null) {
      console.warn('Time tracking failed to start, retrying...');
      TimeTracker.questionViewStartTime = Date.now();
    }
  },

  /**
   * Record time spent on a question (accumulates locally)
   * @param {number} questionId
   */
  recordTimeForQuestion: (questionId) => {
    // If questionViewStartTime is null but we have a currentlyViewingQuestionId,
    // it means tracking didn't start properly (edge case during page load)
    // Use a minimum time of 1 second as fallback
    if (TimeTracker.questionViewStartTime === null) {
      if (TimeTracker.currentlyViewingQuestionId === questionId) {
        console.warn(`Time tracking didn't start properly for question ${questionId}. Using fallback.`);
        const fallbackTime = 1; // At least 1 second
        if (!TimeTracker.pendingTimeUpdates[questionId]) {
          TimeTracker.pendingTimeUpdates[questionId] = 0;
        }
        TimeTracker.pendingTimeUpdates[questionId] += fallbackTime;
        console.log(`Recorded fallback ${fallbackTime}s for question ${questionId}. Total: ${TimeTracker.pendingTimeUpdates[questionId]}s`);
      }
      return;
    }

    const timeSpent = Math.floor((Date.now() - TimeTracker.questionViewStartTime) / 1000);
    // Store time even if it's 0 seconds, but ensure at least 1 second minimum
    const actualTimeSpent = Math.max(1, timeSpent);
    
    if (!TimeTracker.pendingTimeUpdates[questionId]) {
      TimeTracker.pendingTimeUpdates[questionId] = 0;
    }
    TimeTracker.pendingTimeUpdates[questionId] += actualTimeSpent;
    console.log(`Recorded ${actualTimeSpent}s for question ${questionId}. Total: ${TimeTracker.pendingTimeUpdates[questionId]}s`);

    TimeTracker.questionViewStartTime = null;
  },

  /**
   * Record time for currently viewing question and stop tracking
   * Called before submission to ensure last question's time is captured
   */
  recordCurrentQuestion: () => {
    if (TimeTracker.currentlyViewingQuestionId !== null) {
      console.log(`Recording time for current question ${TimeTracker.currentlyViewingQuestionId}`);
      
      // If questionViewStartTime is null, it means tracking wasn't started properly
      // Set it now to capture at least some time
      if (TimeTracker.questionViewStartTime === null) {
        console.warn('Question view start time was null, using current time as fallback');
        TimeTracker.questionViewStartTime = Date.now() - 1000; // Assume at least 1 second
      }
      
      TimeTracker.recordTimeForQuestion(TimeTracker.currentlyViewingQuestionId);
      TimeTracker.currentlyViewingQuestionId = null;
      TimeTracker.questionViewStartTime = null;
    }
  },

  /**
   * Send accumulated time to server periodically
   */
  syncTimeUpdates: async () => {
    if (Object.keys(TimeTracker.pendingTimeUpdates).length === 0) {
      console.log('No pending time updates to sync');
      return;
    }

    const updates = { ...TimeTracker.pendingTimeUpdates };
    TimeTracker.pendingTimeUpdates = {};
    
    console.log('Syncing time updates:', updates);

    try {
      for (const [questionId, timeSpent] of Object.entries(updates)) {
        try {
          const response = await API.trackQuestionTime(TimeTracker.attemptId, parseInt(questionId), timeSpent);
          console.log(`Synced time for question ${questionId}: ${timeSpent}s`);
        } catch (error) {
          console.error(`Failed to sync time for question ${questionId}:`, error);
          // Re-add to pending if failed
          TimeTracker.pendingTimeUpdates[questionId] = (TimeTracker.pendingTimeUpdates[questionId] || 0) + timeSpent;
          throw error;
        }
      }
    } catch (error) {
      console.error('Failed to sync time updates:', error);
      throw error;
    }
  },

  /**
   * Start periodic sync of time updates
   */
  startPeriodicSync: () => {
    // Sync every 5 seconds
    TimeTracker.intervalId = setInterval(() => {
      TimeTracker.syncTimeUpdates();
    }, TimeTracker.updateInterval);

    // Also sync when page is about to unload
    window.addEventListener('beforeunload', () => {
      TimeTracker.recordCurrentQuestion();
      TimeTracker.syncTimeUpdates();
    });
  },

  /**
   * Stop periodic sync
   */
  stopPeriodicSync: () => {
    if (TimeTracker.intervalId) {
      clearInterval(TimeTracker.intervalId);
      TimeTracker.intervalId = null;
    }
  },

  /**
   * Format seconds to MM:SS or HH:MM:SS
   * @param {number} seconds - Total seconds
   * @returns {string} Formatted time
   */
  formatTime: (seconds) => {
    if (!seconds || seconds < 0) return '00:00';

    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;

    if (hours > 0) {
      return `${hours}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
    } else {
      return `${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
    }
  },

  /**
   * Get formatted total time for a question
   * @param {number} questionId
   * @returns {string} Formatted time
   */
  getFormattedTimeForQuestion: (questionId) => {
    let totalSeconds = TimeTracker.pendingTimeUpdates[questionId] || 0;

    // If it's the currently viewed question, add current viewing time
    if (TimeTracker.currentlyViewingQuestionId === questionId && TimeTracker.questionViewStartTime) {
      totalSeconds += Math.floor((Date.now() - TimeTracker.questionViewStartTime) / 1000);
    }

    return TimeTracker.formatTime(totalSeconds);
  },
};

// Make TimeTracker globally accessible
window.TimeTracker = TimeTracker;

// Confirm module loaded
console.log('TimeTracker module loaded successfully');
console.log('TimeTracker object:', TimeTracker);
console.log('window.TimeTracker:', window.TimeTracker);
