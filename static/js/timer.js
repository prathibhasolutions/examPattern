/**
 * Timer Module
 * Handles countdown timer and time tracking
 */

const Timer = {
  startTime: null,
  totalSeconds: 0,
  remainingSeconds: 0,
  timerId: null,
  warningThreshold: 300, // 5 minutes
  isRunning: false,
  isPaused: false,
  pausedAt: null,
  pausedDuration: 0,
  onTimeUpHandler: null,
  onTickHandler: null,

  // Initialize timer with duration in seconds
  init: (totalSeconds, onTimeUp, onTick) => {
    Timer.totalSeconds = totalSeconds;
    Timer.remainingSeconds = totalSeconds;
    Timer.startTime = Date.now();
    Timer.onTimeUpHandler = onTimeUp || null;
    Timer.onTickHandler = onTick || null;
    Timer.start();
  },

  // Start the timer
  start: () => {
    if (Timer.isRunning) return;
    Timer.isRunning = true;
    
    Timer.timerId = setInterval(() => {
      const elapsed = Math.floor((Date.now() - Timer.startTime) / 1000);
      Timer.remainingSeconds = Timer.totalSeconds - elapsed;

      if (Timer.remainingSeconds <= 0) {
        Timer.remainingSeconds = 0;
        Timer.stop();
        Timer.onTimeUp();
        return;
      }

      Timer.render();
      if (typeof Timer.onTickHandler === 'function') {
        Timer.onTickHandler(Timer.remainingSeconds);
      }
    }, 1000);
  },

  // Stop the timer
  stop: () => {
    Timer.isRunning = false;
    clearInterval(Timer.timerId);
  },

  // Pause the timer
  pause: () => {
    if (!Timer.isRunning || Timer.isPaused) return;
    
    Timer.isPaused = true;
    Timer.isRunning = false;
    Timer.pausedAt = Date.now();
    clearInterval(Timer.timerId);
    
    const timerEl = document.getElementById('timer');
    if (timerEl) {
      timerEl.classList.add('paused');
    }
  },

  // Resume the timer
  resume: () => {
    if (!Timer.isPaused) return;
    
    Timer.isPaused = false;
    
    // Calculate how long we were paused and adjust start time
    if (Timer.pausedAt) {
      const pausedTime = Math.floor((Date.now() - Timer.pausedAt) / 1000);
      Timer.pausedDuration += pausedTime;
      Timer.startTime += pausedTime * 1000;
      Timer.pausedAt = null;
    }
    
    const timerEl = document.getElementById('timer');
    if (timerEl) {
      timerEl.classList.remove('paused');
    }
    
    Timer.start();
  },

  // Render timer to DOM
  render: () => {
    const timerEl = document.getElementById('timer');
    if (!timerEl) return;

    const mins = Math.floor(Timer.remainingSeconds / 60);
    const secs = Timer.remainingSeconds % 60;
    timerEl.textContent = `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;

    // Apply color based on remaining time
    timerEl.classList.remove('warning', 'danger');
    if (Timer.remainingSeconds <= Timer.warningThreshold && Timer.remainingSeconds > 60) {
      timerEl.classList.add('warning');
    } else if (Timer.remainingSeconds <= 60) {
      timerEl.classList.add('danger');
    }
  },

  setDisplayText: (text) => {
    const timerEl = document.getElementById('timer');
    if (!timerEl) return;
    timerEl.textContent = text;
    timerEl.classList.remove('warning', 'danger');
  },

  // Called when time runs out
  onTimeUp: () => {
    if (typeof Timer.onTimeUpHandler === 'function') {
      Timer.onTimeUpHandler();
      return;
    }

    console.log('Time limit exceeded - Auto-submitting test');
    
    // Show time up modal/message
    const timeUpToast = document.createElement('div');
    timeUpToast.className = 'alert alert-danger position-fixed top-0 start-50 translate-middle-x mt-3';
    timeUpToast.style.zIndex = '9999';
    timeUpToast.innerHTML = '<i class="fas fa-clock me-2"></i><strong>Time is up!</strong> Your test will be submitted automatically.';
    document.body.appendChild(timeUpToast);
    
    // Auto-submit (handled by main app)
    setTimeout(() => {
      if (window.testApp && window.testApp.submitAttempt) {
        window.testApp.submitAttempt();
      }
    }, 2000);
  },

  // Get elapsed seconds
  getElapsed: () => {
    return Timer.totalSeconds - Timer.remainingSeconds;
  },
};
