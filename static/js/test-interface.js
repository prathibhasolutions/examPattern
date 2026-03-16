/**
 * Main Test Interface App
 * Orchestrates all modules
 */

const testApp = {
  attempt: null,
  test: null,
  questions: [],
  sections: [],
  sectionOrder: [],
  sectionMetaById: {},
  currentSectionId: null,
  sectionRemainingSeconds: {},
  useSectionalTiming: false,
  pendingSectionSwitchQuestionId: null,
  allowSectionSwitch: false,
  forceSectionSwitch: false,
  timerHeartbeatId: null,

  // Initialize app
  init: async () => {
    try {
      if (!ATTEMPT_ID || !TEST_ID) {
        console.error('Missing ATTEMPT_ID or TEST_ID');
        return;
      }

      // Fetch attempt and test data
      testApp.attempt = await API.getAttempt(ATTEMPT_ID);
      testApp.test = await API.getTest(TEST_ID);

      // If attempt is already submitted, redirect to results and prevent back navigation
      if (testApp.attempt.status === 'submitted') {
        window.location.replace(`/results/${ATTEMPT_ID}/`);
        return;
      }

      console.log('Test loaded:', testApp.test);
      console.log('Sections:', testApp.test.sections);

      testApp.useSectionalTiming = !!testApp.test.use_sectional_timing;

      // Build question list with section context and current status/answers
      const answersByQuestion = Object.fromEntries(
        (testApp.attempt.answers || []).map(a => [a.question, a])
      );

      const questions = [];
      const sections = [...(testApp.test.sections || [])].sort((a, b) => (a.order || 0) - (b.order || 0));
      testApp.sections = sections;
      testApp.sectionOrder = sections.map(s => s.id);
      testApp.sectionMetaById = sections.reduce((acc, section) => {
        acc[section.id] = {
          id: section.id,
          name: section.name,
          order: section.order || 0,
          timeLimitSeconds: section.time_limit_seconds || 0,
          firstQuestionId: null,
        };
        return acc;
      }, {});

      sections.forEach(section => {
        let sectionQuestionNumber = 1; // Reset for each section
        (section.questions || []).forEach(q => {
          const ans = answersByQuestion[q.id] || {};
          if (!testApp.sectionMetaById[section.id].firstQuestionId) {
            testApp.sectionMetaById[section.id].firstQuestionId = q.id;
          }
          questions.push({
            ...q,
            section_id: section.id,
            section_name: section.name,
            section_order: section.order,
            question_number: sectionQuestionNumber,
            global_question_number: questions.length + 1,
            status: ans.status || 'not_visited',
            selected_option_ids: ans.selected_option_ids || [],
            response_text: ans.response_text || '',
          });
          sectionQuestionNumber++;
        });
      });
      testApp.questions = questions;

      console.log('Questions loaded:', questions.length);
      console.log('First question:', questions[0]);

      // Initialize per-section remaining time if sectional timing is enabled
      if (testApp.useSectionalTiming) {
        testApp.sectionOrder.forEach(sectionId => {
          const meta = testApp.sectionMetaById[sectionId];
          // Subtract already-spent time so the timer resumes from where it stopped
          const spentSeconds = (testApp.attempt.section_timings || {})[String(sectionId)] || 0;
          testApp.sectionRemainingSeconds[sectionId] = Math.max(0, (meta.timeLimitSeconds || 0) - spentSeconds);
        });
      }

      // Initialize modules
      Navigation.init(questions.length);
      UI.initAnswers(testApp.attempt.answers);
      Palette.init(questions, sections);

      // Render section tabs
      testApp.renderSectionTabs();
      
      // Set initial section
      if (sections.length > 0) {
        testApp.currentSectionId = sections[0].id;
        testApp.updateActiveSectionTab(sections[0].id);
        // Filter palette by first section
        if (Palette && typeof Palette.filterBySection === 'function') {
          Palette.filterBySection(sections[0].id);
        }
        console.log('Initial section set:', sections[0].name);
      } else {
        console.warn('No sections found!');
      }

      // Initialize timer
      if (testApp.useSectionalTiming && testApp.sectionOrder.length > 0) {
        const firstSectionId = testApp.sectionOrder[0];
        testApp.currentSectionId = firstSectionId;
        testApp.startSectionTimer(firstSectionId);
      } else {
        const timingInfo = await API.checkTiming(ATTEMPT_ID);
        const initialSeconds = timingInfo.remaining_seconds ?? timingInfo.total_duration;
        if (initialSeconds && initialSeconds > 0) {
          Timer.init(initialSeconds);
          // Save immediately so DB has a valid value from the very first second
          API.saveTimer(ATTEMPT_ID, initialSeconds);
          // Heartbeat: save remaining time every 10 s so resume starts from correct point
          testApp.timerHeartbeatId = setInterval(() => {
            if (Timer.isRunning && Timer.remainingSeconds > 0) {
              API.saveTimer(ATTEMPT_ID, Timer.remainingSeconds);
            }
          }, 10000);
        } else {
          Timer.setDisplayText('No Limit');
        }
      }

      // Initialize time tracker
      console.log('Checking TimeTracker availability...');
      console.log('window.TimeTracker:', window.TimeTracker);
      console.log('window.TimeTracker type:', typeof window.TimeTracker);
      if (window.TimeTracker && typeof window.TimeTracker.init === 'function') {
        console.log('Initializing TimeTracker with attemptId:', ATTEMPT_ID);
        TimeTracker.init(ATTEMPT_ID);
        
        // Small delay to ensure TimeTracker is fully initialized before selecting first question
        await new Promise(resolve => setTimeout(resolve, 100));
      } else {
        console.warn('TimeTracker not available or init is not a function');
      }

      // Select first question
      const firstQuestion = questions[0];
      if (firstQuestion) {
        testApp.selectQuestion(firstQuestion.id);
        
        // Double-check that time tracking started for the first question
        if (window.TimeTracker && typeof window.TimeTracker.startTracking === 'function') {
          if (TimeTracker.currentlyViewingQuestionId !== firstQuestion.id || TimeTracker.questionViewStartTime === null) {
            console.warn('First question time tracking not started properly, starting now');
            TimeTracker.startTracking(firstQuestion.id);
          }
        }
      }

      // Attach event listeners
      testApp.attachEventListeners();
    } catch (error) {
      console.error('Failed to initialize test:', error);
      
      // Show error toast instead of alert
      const errorToast = document.createElement('div');
      errorToast.className = 'alert alert-danger position-fixed top-0 start-50 translate-middle-x mt-3';
      errorToast.style.zIndex = '9999';
      errorToast.innerHTML = '<i class="fas fa-exclamation-triangle me-2"></i>Failed to load test. Please refresh the page.';
      document.body.appendChild(errorToast);
    }
  },

  // Select and display a question
  selectQuestion: (questionId) => {
    UI.selectQuestion(questionId);
  },

  // Determine if navigation to a question is allowed in sectional timing
  canNavigateToQuestion: (questionId) => {
    if (!testApp.useSectionalTiming) return true;
    if (testApp.forceSectionSwitch) return true;

    const targetQuestion = Palette.getQuestion(questionId);
    if (!targetQuestion) return true;

    if (!testApp.currentSectionId) {
      testApp.currentSectionId = targetQuestion.section_id;
      return true;
    }

    const targetSectionId = targetQuestion.section_id;
    if (targetSectionId === testApp.currentSectionId) return true;

    const currentIndex = testApp.sectionOrder.indexOf(testApp.currentSectionId);
    const targetIndex = testApp.sectionOrder.indexOf(targetSectionId);

    if (targetIndex < currentIndex) {
      testApp.showSectionBlockedToast('Previous sections are locked.');
      return false;
    }

    if (targetIndex > currentIndex + 1) {
      testApp.showSectionBlockedToast('You must complete this section before accessing later sections.');
      return false;
    }

    // Moving to next section
    if (targetIndex === currentIndex + 1) {
      if (testApp.allowSectionSwitch && testApp.pendingSectionSwitchQuestionId === questionId) {
        testApp.allowSectionSwitch = false;
        testApp.pendingSectionSwitchQuestionId = null;
        return true;
      }

      if (Timer.remainingSeconds > 0) {
        testApp.pendingSectionSwitchQuestionId = questionId;
        const sectionSwitchModal = new bootstrap.Modal(document.getElementById('sectionSwitchModal'));
        sectionSwitchModal.show();
        return false;
      }

      return true;
    }

    return true;
  },

  // Handle section change in sectional timing mode
  handleSectionChange: (nextSectionId) => {
    if (!nextSectionId) return;
    
    // Update palette to show only questions from this section
    if (Palette && typeof Palette.filterBySection === 'function') {
      Palette.filterBySection(nextSectionId);
    }
    
    if (!testApp.useSectionalTiming) {
      testApp.currentSectionId = nextSectionId;
      return;
    }
    
    if (testApp.currentSectionId === nextSectionId) return;

    // Save remaining time for current section
    if (testApp.currentSectionId && Timer.isRunning) {
      const elapsed = Timer.getElapsed();
      const currentRemaining = testApp.sectionRemainingSeconds[testApp.currentSectionId] || 0;
      testApp.sectionRemainingSeconds[testApp.currentSectionId] = Math.max(0, currentRemaining - elapsed);
    }

    testApp.currentSectionId = nextSectionId;
    testApp.startSectionTimer(nextSectionId);
  },

  // Start or resume timer for a section
  startSectionTimer: (sectionId) => {
    const remaining = testApp.sectionRemainingSeconds[sectionId] || 0;
    if (remaining <= 0) {
      Timer.stop();
      Timer.setDisplayText('No Limit');
      return;
    }

    Timer.stop();
    Timer.init(remaining, () => testApp.onSectionTimeUp());
  },

  // Handle section time up
  onSectionTimeUp: () => {
    Timer.stop();

    const currentIndex = testApp.sectionOrder.indexOf(testApp.currentSectionId);
    const nextIndex = currentIndex + 1;

    if (nextIndex < testApp.sectionOrder.length) {
      const nextSectionId = testApp.sectionOrder[nextIndex];
      const nextMeta = testApp.sectionMetaById[nextSectionId];

      const timeUpToast = document.createElement('div');
      timeUpToast.className = 'alert alert-warning position-fixed top-0 start-50 translate-middle-x mt-3';
      timeUpToast.style.zIndex = '9999';
      timeUpToast.innerHTML = `<i class="fas fa-clock me-2"></i><strong>Section time is up!</strong> Moving to ${nextMeta?.name || 'next section'}...`;
      document.body.appendChild(timeUpToast);

      setTimeout(() => {
        timeUpToast.remove();
        testApp.forceSectionSwitch = true;
        if (nextMeta && nextMeta.firstQuestionId) {
          testApp.selectQuestion(nextMeta.firstQuestionId);
        }
        testApp.handleSectionChange(nextSectionId);
        testApp.forceSectionSwitch = false;
      }, 1500);
      return;
    }

    const finalToast = document.createElement('div');
    finalToast.className = 'alert alert-danger position-fixed top-0 start-50 translate-middle-x mt-3';
    finalToast.style.zIndex = '9999';
    finalToast.innerHTML = '<i class="fas fa-clock me-2"></i><strong>Final section time is up!</strong> Submitting your test...';
    document.body.appendChild(finalToast);

    setTimeout(() => {
      finalToast.remove();
      if (window.testApp && window.testApp.submitAttempt) {
        window.testApp.submitAttempt();
      }
    }, 2000);
  },

  showSectionBlockedToast: (message) => {
    const toast = document.createElement('div');
    toast.className = 'alert alert-info position-fixed top-0 start-50 translate-middle-x mt-3';
    toast.style.zIndex = '9999';
    toast.innerHTML = `<i class="fas fa-info-circle me-2"></i>${message}`;
    document.body.appendChild(toast);

    setTimeout(() => {
      toast.remove();
    }, 2000);
  },

  // Render section tabs
  renderSectionTabs: () => {
    const sectionsBarEl = document.getElementById('sectionsBar');
    if (!sectionsBarEl) return;

    sectionsBarEl.innerHTML = '';
    testApp.sections.forEach((section, index) => {
      const tab = document.createElement('button');
      tab.className = 'section-tab';
      tab.textContent = section.name || `Section ${index + 1}`;
      tab.dataset.sectionId = section.id;
      if (index === 0) tab.classList.add('active');
      
      tab.addEventListener('click', () => {
        const firstQuestionInSection = testApp.questions.find(q => q.section_id === section.id);
        if (firstQuestionInSection) {
          UI.selectQuestion(firstQuestionInSection.id);
        }
      });
      
      sectionsBarEl.appendChild(tab);
    });
  },

  // Update active section tab
  updateActiveSectionTab: (sectionId) => {
    document.querySelectorAll('.section-tab').forEach(tab => {
      tab.classList.remove('active');
      if (tab.dataset.sectionId === String(sectionId)) {
        tab.classList.add('active');
      }
    });

    // Update palette header
    const section = testApp.sections.find(s => s.id === sectionId);
    const paletteHeaderEl = document.getElementById('paletteHeader');
    if (paletteHeaderEl && section) {
      paletteHeaderEl.textContent = `SECTION: ${section.name}`;
    }
  },

  // Update question number display
  updateQuestionNumber: (questionId) => {
    const question = testApp.questions.find(q => q.id === questionId);
    const questionNumberEl = document.getElementById('questionNumber');
    if (questionNumberEl && question) {
      questionNumberEl.textContent = `Question ${question.question_number}`;
    }
  },

  // Submit attempt
  submitAttempt: async () => {
    try {
      // Mark as submitting to prevent beforeunload warning
      testApp.isSubmitting = true;
      
      // Record and sync time tracker before submitting
      if (window.TimeTracker && typeof window.TimeTracker.recordCurrentQuestion === 'function') {
        TimeTracker.recordCurrentQuestion();
        
        // Stop periodic sync to avoid conflicts
        if (typeof TimeTracker.stopPeriodicSync === 'function') {
          TimeTracker.stopPeriodicSync();
        }
        
        // Sync time updates and wait for completion
        await TimeTracker.syncTimeUpdates();
        
        // Add small delay to ensure requests are processed
        await new Promise(resolve => setTimeout(resolve, 500));
      }
      
      Timer.stop();
      // Clear heartbeat interval
      if (testApp.timerHeartbeatId) {
        clearInterval(testApp.timerHeartbeatId);
        testApp.timerHeartbeatId = null;
      }
      const result = await API.submitAttempt(ATTEMPT_ID);
      
      // Redirect to results page immediately with success parameter
      window.location.replace(`/results/${ATTEMPT_ID}/?submitted=true`);
    } catch (error) {
      console.error('Failed to submit:', error);
      testApp.isSubmitting = false;
      
      const errorToast = document.createElement('div');
      errorToast.className = 'alert alert-danger position-fixed top-0 start-50 translate-middle-x mt-3';
      errorToast.style.zIndex = '9999';
      errorToast.innerHTML = '<i class="fas fa-exclamation-triangle me-2"></i>Failed to submit test. Please try again.';
      document.body.appendChild(errorToast);
      
      setTimeout(() => {
        errorToast.remove();
      }, 3000);
      
      // Restart timer if submission failed
      Timer.start();
    }
  },

  // Attach event listeners
  attachEventListeners: () => {
    // Navigation buttons
    document.getElementById('btn-prev')?.addEventListener('click', () => {
      Navigation.prev();
    });

    document.getElementById('btn-next')?.addEventListener('click', () => {
      Navigation.next();
    });
    // Clear response button
    document.getElementById('btn-clear')?.addEventListener('click', () => {
      UI.clearResponse();
    });
    // Mark for review button
    document.getElementById('btn-mark-review')?.addEventListener('click', () => {
      UI.markForReview();
    });

    // Submit button - show modal instead of direct submit
    document.getElementById('btn-submit')?.addEventListener('click', () => {
      const submitModal = new bootstrap.Modal(document.getElementById('submitConfirmModal'));
      submitModal.show();
    });

    // Confirm submit button in modal
    document.getElementById('confirmSubmitBtn')?.addEventListener('click', () => {
      const submitModal = bootstrap.Modal.getInstance(document.getElementById('submitConfirmModal'));
      submitModal.hide();
      testApp.submitAttempt();
    });

    // Section switch modal
    document.getElementById('confirmSectionSwitchBtn')?.addEventListener('click', () => {
      const switchModal = bootstrap.Modal.getInstance(document.getElementById('sectionSwitchModal'));
      switchModal.hide();
      testApp.allowSectionSwitch = true;
      const pendingId = testApp.pendingSectionSwitchQuestionId;
      if (pendingId) {
        testApp.selectQuestion(pendingId);
      }
    });

    document.getElementById('cancelSectionSwitchBtn')?.addEventListener('click', () => {
      testApp.allowSectionSwitch = false;
      testApp.pendingSectionSwitchQuestionId = null;
    });

    // Handle leave test modal
    let leaveConfirmed = false;
    
    document.getElementById('confirmLeaveBtn')?.addEventListener('click', () => {
      leaveConfirmed = true;
      const leaveModal = bootstrap.Modal.getInstance(document.getElementById('leaveTestModal'));
      leaveModal.hide();
      // Allow the page to unload after confirmation
      window.location.href = '/tests/';
    });

    document.getElementById('cancelLeaveBtn')?.addEventListener('click', () => {
      leaveConfirmed = false;
    });

    // Replace default beforeunload with modal
    window.addEventListener('beforeunload', (e) => {
      // Save timer FIRST — sendBeacon is fire-and-forget and must be called
      // before any return/prevent-default that would block further execution
      if (!testApp.isSubmitting && Timer.remainingSeconds > 0) {
        API.saveTimerBeacon(ATTEMPT_ID, Timer.remainingSeconds);
      }

      if (!testApp.isSubmitting && testApp.attempt && testApp.attempt.status === 'in_progress' && !leaveConfirmed) {
        e.preventDefault();
        e.returnValue = '';
        
        // Show the Bootstrap modal instead
        const leaveModal = new bootstrap.Modal(document.getElementById('leaveTestModal'));
        leaveModal.show();
        
        return false;
      }
    });
  },
};

// Initialize app when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
  testApp.init();
});

// Make testApp globally available
window.testApp = testApp;
