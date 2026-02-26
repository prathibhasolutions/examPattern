/**
 * Utility Module
 * Shared utility functions
 */

const Utils = {
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
   * Format time comparison (e.g., "50:30/1:00:00")
   * @param {number} timeSpent - Seconds spent
   * @param {number} totalTime - Total available time in seconds
   * @returns {string} Formatted time comparison
   */
  formatTimeComparison: (timeSpent, totalTime) => {
    return `${Utils.formatTime(timeSpent)}/${Utils.formatTime(totalTime)}`;
  },
};
