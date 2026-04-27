/**
 * Offline Answer Queue
 * Buffers failed saves in localStorage so they can be retried on reconnect,
 * and stores a full pending-submission snapshot when submit fails offline.
 */
const OfflineQueue = {
  queueKey: () => `exam_answer_queue_${ATTEMPT_ID}`,
  pendingKey: () => `exam_pending_submission_${ATTEMPT_ID}`,
  snapshotKey: () => `exam_answer_snapshot_${ATTEMPT_ID}`,

  // Add a failed answer to the retry queue
  enqueue: (questionId, payload) => {
    try {
      const raw = localStorage.getItem(OfflineQueue.queueKey());
      const queue = raw ? JSON.parse(raw) : {};
      queue[questionId] = payload;
      localStorage.setItem(OfflineQueue.queueKey(), JSON.stringify(queue));
    } catch (e) {
      console.warn('OfflineQueue.enqueue failed:', e);
    }
  },

  // Flush queued answers to the server
  flush: async () => {
    let queue;
    try {
      const raw = localStorage.getItem(OfflineQueue.queueKey());
      queue = raw ? JSON.parse(raw) : {};
    } catch (e) {
      return;
    }
    const ids = Object.keys(queue);
    if (!ids.length) return;

    const failed = {};
    for (const qId of ids) {
      try {
        await API.saveAnswer(ATTEMPT_ID, queue[qId]);
        if (UI.answers[qId]) UI.answers[qId]._savedToServer = true;
      } catch (e) {
        failed[qId] = queue[qId];
      }
    }
    if (Object.keys(failed).length) {
      localStorage.setItem(OfflineQueue.queueKey(), JSON.stringify(failed));
    } else {
      localStorage.removeItem(OfflineQueue.queueKey());
    }
  },

  // Flush every in-memory answer that has not yet been confirmed saved.
  // Sends all unsaved answers IN PARALLEL (Promise.allSettled) so even 160
  // answers complete in one round-trip time instead of 160 sequential ones.
  // This must be awaited before calling API.submitAttempt().
  flushUnsavedAnswers: async () => {
    const answers = UI.answers || {};
    const tasks = [];
    const failed = {};
    for (const [qId, answer] of Object.entries(answers)) {
      if (answer.status === 'not_visited') continue;
      if (answer._savedToServer) continue; // already confirmed on server
      const payload = {
        question: parseInt(qId),
        selected_option_ids: answer.selected_option_ids || [],
        response_text: answer.response_text || '',
        status: answer.status || 'visited',
        // time_spent_seconds intentionally omitted — tracked exclusively via
        // track_question_time which accumulates; sending 0 here would overwrite it.
      };
      tasks.push(
        API.saveAnswer(ATTEMPT_ID, payload)
          .then(() => { if (UI.answers[qId]) UI.answers[qId]._savedToServer = true; })
          .catch(() => {
            failed[qId] = payload;
            if (UI.answers[qId]) UI.answers[qId]._savedToServer = false;
          })
      );
    }
    if (tasks.length) await Promise.allSettled(tasks);

    if (Object.keys(failed).length) {
      let existing = {};
      try {
        const raw = localStorage.getItem(OfflineQueue.queueKey());
        existing = raw ? JSON.parse(raw) : {};
      } catch (_e) {
        existing = {};
      }
      localStorage.setItem(OfflineQueue.queueKey(), JSON.stringify({ ...existing, ...failed }));
    } else {
      localStorage.removeItem(OfflineQueue.queueKey());
    }
  },

  // Flush every in-memory answer to server (called just before submitting)
  flushAllAnswers: async () => {
    const answers = UI.answers || {};
    for (const [qId, answer] of Object.entries(answers)) {
      if (answer.status === 'not_visited') continue;
      try {
        await API.saveAnswer(ATTEMPT_ID, {
          question: parseInt(qId),
          selected_option_ids: answer.selected_option_ids || [],
          response_text: answer.response_text || '',
          status: answer.status || 'visited',
        });
        if (UI.answers[qId]) UI.answers[qId]._savedToServer = true;
      } catch (e) {
        // Continue — if we're offline, submit will fail and trigger localStorage save
      }
    }
    localStorage.removeItem(OfflineQueue.queueKey());
  },

  // Persist full answer state + metadata for deferred submission
  savePendingSubmission: (attemptId, answers, timerRemaining) => {
    try {
      const cleanAnswers = {};
      for (const [qId, answer] of Object.entries(answers || {})) {
        cleanAnswers[qId] = {
          question: parseInt(qId),
          selected_option_ids: answer.selected_option_ids || [],
          response_text: answer.response_text || '',
          status: answer.status || 'not_visited',
        };
      }
      localStorage.setItem(OfflineQueue.pendingKey(), JSON.stringify({
        attemptId,
        answers: cleanAnswers,
        timerRemaining,
        savedAt: Date.now(),
      }));
    } catch (e) {
      console.warn('OfflineQueue.savePendingSubmission failed:', e);
    }
  },

  // Remove pending submission after successful submit
  clearPendingSubmission: () => {
    localStorage.removeItem(OfflineQueue.pendingKey());
    localStorage.removeItem(OfflineQueue.queueKey());
    localStorage.removeItem(OfflineQueue.snapshotKey());
  },

  // Persist a durable local snapshot of answers so a browser restart or
  // backend outage does not lose in-progress work.
  saveAnswerSnapshot: (answers) => {
    try {
      const cleanAnswers = {};
      for (const [qId, answer] of Object.entries(answers || {})) {
        cleanAnswers[qId] = {
          question: parseInt(qId),
          selected_option_ids: answer.selected_option_ids || [],
          response_text: answer.response_text || '',
          status: answer.status || 'not_visited',
        };
      }
      localStorage.setItem(OfflineQueue.snapshotKey(), JSON.stringify({
        savedAt: Date.now(),
        answers: cleanAnswers,
      }));
    } catch (e) {
      console.warn('OfflineQueue.saveAnswerSnapshot failed:', e);
    }
  },

  loadAnswerSnapshot: () => {
    try {
      const raw = localStorage.getItem(OfflineQueue.snapshotKey());
      return raw ? JSON.parse(raw) : null;
    } catch (_e) {
      return null;
    }
  },

  loadPendingSubmission: () => {
    try {
      const raw = localStorage.getItem(OfflineQueue.pendingKey());
      return raw ? JSON.parse(raw) : null;
    } catch (_e) {
      return null;
    }
  },
};

window.OfflineQueue = OfflineQueue;

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
  isOffline: false,
  pendingSubmitOnReconnect: false,
  answerSnapshotHeartbeatId: null,

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
      testApp.continuousNumbering = !!testApp.test.continuous_numbering;

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
        // Apply shuffled question order if this attempt has one for this section
        const shuffledQIds = (testApp.attempt.question_order || {})[String(section.id)];
        let sectionQuestions = section.questions || [];
        if (shuffledQIds && shuffledQIds.length) {
          // Re-sort the questions array to match the stored shuffle order
          const qById = Object.fromEntries(sectionQuestions.map(q => [q.id, q]));
          sectionQuestions = shuffledQIds.map(id => qById[id]).filter(Boolean);
        }

        // Apply shuffled option order per question
        const optionOrderMap = testApp.attempt.option_order || {};

        let sectionQuestionNumber = 1; // Reset for each section
        sectionQuestions.forEach(q => {
          // Reorder options if a shuffle order is stored for this question
          const shuffledOptIds = optionOrderMap[String(q.id)];
          let orderedOptions = q.options || [];
          if (shuffledOptIds && shuffledOptIds.length) {
            const optById = Object.fromEntries(orderedOptions.map(o => [o.id, o]));
            orderedOptions = shuffledOptIds.map(id => optById[id]).filter(Boolean);
          }

          const ans = answersByQuestion[q.id] || {};
          if (!testApp.sectionMetaById[section.id].firstQuestionId) {
            testApp.sectionMetaById[section.id].firstQuestionId = q.id;
          }
          questions.push({
            ...q,
            options: orderedOptions,
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

      // If continuous numbering is enabled, override question_number with global sequence
      if (testApp.continuousNumbering) {
        testApp.questions.forEach(q => { q.question_number = q.global_question_number; });
      }

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

      // Merge a local snapshot captured on this device (if any). This recovers
      // answers that never reached the backend during transient outages.
      const localSnapshot = OfflineQueue.loadAnswerSnapshot();
      if (localSnapshot && localSnapshot.answers) {
        for (const [qId, snapshotAnswer] of Object.entries(localSnapshot.answers)) {
          const hasMeaningfulValue =
            (snapshotAnswer.response_text || '').trim().length > 0 ||
            (snapshotAnswer.selected_option_ids || []).length > 0 ||
            (snapshotAnswer.status && snapshotAnswer.status !== 'not_visited');
          if (!hasMeaningfulValue) continue;

          UI.answers[qId] = {
            ...(UI.answers[qId] || { question: parseInt(qId) }),
            selected_option_ids: snapshotAnswer.selected_option_ids || [],
            response_text: snapshotAnswer.response_text || '',
            status: snapshotAnswer.status || 'visited',
            _savedToServer: false,
            _saveSeq: (UI.answers[qId]?._saveSeq || 0) + 1,
          };
        }
      }

      // Recover a pending submission captured during a prior outage/reload.
      const pendingSubmission = OfflineQueue.loadPendingSubmission();
      if (pendingSubmission && pendingSubmission.answers) {
        for (const [qId, pendingAnswer] of Object.entries(pendingSubmission.answers)) {
          const hasMeaningfulValue =
            (pendingAnswer.response_text || '').trim().length > 0 ||
            (pendingAnswer.selected_option_ids || []).length > 0 ||
            (pendingAnswer.status && pendingAnswer.status !== 'not_visited');
          if (!hasMeaningfulValue) continue;

          UI.answers[qId] = {
            ...(UI.answers[qId] || { question: parseInt(qId) }),
            selected_option_ids: pendingAnswer.selected_option_ids || [],
            response_text: pendingAnswer.response_text || '',
            status: pendingAnswer.status || 'visited',
            _savedToServer: false,
            _saveSeq: (UI.answers[qId]?._saveSeq || 0) + 1,
          };
        }

        if (testApp.attempt?.status === 'in_progress') {
          const existing = document.getElementById('pending-submit-toast');
          if (existing) existing.remove();

          const recoverToast = document.createElement('div');
          recoverToast.id = 'pending-submit-toast';
          recoverToast.className = 'alert alert-warning position-fixed bottom-0 start-50 translate-middle-x mb-3';
          recoverToast.style.zIndex = '9999';
          recoverToast.style.maxWidth = '560px';
          recoverToast.style.fontSize = '14px';
          recoverToast.innerHTML =
            '<i class="fas fa-history me-2"></i>' +
            '<strong>Recovered unsent answers from this device.</strong> Please click Submit again to safely finalize.';
          document.body.appendChild(recoverToast);
        }
      }

      Palette.init(questions, sections);

      // Keep a periodic snapshot of current UI answers in localStorage.
      testApp.answerSnapshotHeartbeatId = setInterval(() => {
        OfflineQueue.saveAnswerSnapshot(UI.answers || {});
      }, 5000);

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

      // All done — hide the page-load overlay
      const pageLoadOverlay = document.getElementById('page-load-overlay');
      if (pageLoadOverlay) pageLoadOverlay.style.display = 'none';
    } catch (error) {
      console.error('Failed to initialize test:', error);

      // Hide page-load overlay so the error toast is visible
      const pageLoadOverlay = document.getElementById('page-load-overlay');
      if (pageLoadOverlay) pageLoadOverlay.style.display = 'none';

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

      // Show full-screen overlay so users know submission is in progress
      const submitOverlay = document.getElementById('submit-overlay');
      if (submitOverlay) submitOverlay.style.display = 'flex';

      // Record and stop time tracking — fire sync in the background without
      // waiting so it doesn't block the submit response. Time-spent data is
      // analytics only and does not affect scoring.
      if (window.TimeTracker && typeof window.TimeTracker.recordCurrentQuestion === 'function') {
        TimeTracker.recordCurrentQuestion();
        if (typeof TimeTracker.stopPeriodicSync === 'function') {
          TimeTracker.stopPeriodicSync();
        }
        // Fire-and-forget: do not await — this could be 160 sequential requests
        TimeTracker.syncTimeUpdates();
      }

      Timer.stop();
      if (testApp.timerHeartbeatId) {
        clearInterval(testApp.timerHeartbeatId);
        testApp.timerHeartbeatId = null;
      }
      if (testApp.answerSnapshotHeartbeatId) {
        clearInterval(testApp.answerSnapshotHeartbeatId);
        testApp.answerSnapshotHeartbeatId = null;
      }

      // Flush answers not yet confirmed saved to the server.
      // We race against a 6-second timeout: if the server is slow, we skip
      // the pre-submit flush and rely on the `fa` payload sent with submit
      // (which already contains every answered question) instead of blocking
      // the submission indefinitely.
      const flushTimeout = new Promise(resolve => setTimeout(resolve, 6000));
      await Promise.race([OfflineQueue.flushUnsavedAnswers(), flushTimeout]);

      // Fire-and-forget the offline retry queue — sequential saves could stall
      // submit for a long time if many retries are queued.  The submit payload
      // (fa) carries the authoritative final answer state anyway.
      OfflineQueue.flush().catch(() => {});

      OfflineQueue.saveAnswerSnapshot(UI.answers || {});

      const finalAnswers = [];
      const answers = UI.answers || {};
      for (const [qId, answer] of Object.entries(answers)) {
        if ((answer.status || 'not_visited') === 'not_visited') continue;

        const compact = {
          q: parseInt(qId),
          s: answer.status || 'visited',
        };
        if ((answer.selected_option_ids || []).length) {
          compact.o = answer.selected_option_ids;
        }
        if ((answer.response_text || '').trim().length) {
          compact.t = answer.response_text;
        }
        finalAnswers.push(compact);
      }

      try {
        await API.submitAttempt(ATTEMPT_ID, { fa: finalAnswers });
        OfflineQueue.clearPendingSubmission();
        // Redirect to the submitted page — evaluation runs in the background
        // there, so this redirect is instant and the student sees a nice screen.
        window.location.replace(`/submitted/${ATTEMPT_ID}/`);
      } catch (submitError) {
        // Never assume submission succeeded when backend returns 5xx.
        // We first probe latest attempt status, then decide whether to redirect.
        const status = submitError?.status;
        const isNetworkError = submitError instanceof TypeError || !status;
        let latestAttempt = null;
        try {
          latestAttempt = await API.getAttempt(ATTEMPT_ID);
        } catch (_e) {
          latestAttempt = null;
        }

        if (latestAttempt?.status === 'submitted') {
          OfflineQueue.clearPendingSubmission();
          window.location.replace(`/submitted/${ATTEMPT_ID}/`);
          return;
        }

        if (isNetworkError) {
          // Truly offline — queue for auto-retry on reconnect
          OfflineQueue.savePendingSubmission(ATTEMPT_ID, UI.answers, Timer.remainingSeconds);
          OfflineQueue.saveAnswerSnapshot(UI.answers || {});
          testApp.pendingSubmitOnReconnect = true;
          testApp.isSubmitting = false;
          if (submitOverlay) submitOverlay.style.display = 'none';

          const existing = document.getElementById('pending-submit-toast');
          if (existing) existing.remove();

          const pendingToast = document.createElement('div');
          pendingToast.id = 'pending-submit-toast';
          pendingToast.className = 'alert alert-warning position-fixed bottom-0 start-50 translate-middle-x mb-3';
          pendingToast.style.zIndex = '9999';
          pendingToast.style.maxWidth = '500px';
          pendingToast.style.fontSize = '14px';
          pendingToast.innerHTML =
            '<i class="fas fa-cloud-upload-alt me-2"></i>' +
            '<strong>No internet.</strong> Your answers are saved on this device and will be submitted automatically once you\'re back online.';
          document.body.appendChild(pendingToast);
        } else if (status >= 500) {
          OfflineQueue.savePendingSubmission(ATTEMPT_ID, UI.answers, Timer.remainingSeconds);
          OfflineQueue.saveAnswerSnapshot(UI.answers || {});
          testApp.isSubmitting = false;
          if (submitOverlay) submitOverlay.style.display = 'none';

          const existing = document.getElementById('pending-submit-toast');
          if (existing) existing.remove();

          const retryToast = document.createElement('div');
          retryToast.id = 'pending-submit-toast';
          retryToast.className = 'alert alert-warning position-fixed bottom-0 start-50 translate-middle-x mb-3';
          retryToast.style.zIndex = '9999';
          retryToast.style.maxWidth = '560px';
          retryToast.style.fontSize = '14px';
          retryToast.innerHTML =
            '<i class="fas fa-server me-2"></i>' +
            '<strong>Server is temporarily unavailable.</strong> Your answers are safe on this device. Please click Submit again in a minute.';
          document.body.appendChild(retryToast);
        } else {
          testApp.isSubmitting = false;
          if (submitOverlay) submitOverlay.style.display = 'none';
          const msg = submitError?.data?.error || 'Submission failed. Please review and try again.';
          const errorToast = document.createElement('div');
          errorToast.className = 'alert alert-danger position-fixed top-0 start-50 translate-middle-x mt-3';
          errorToast.style.zIndex = '9999';
          errorToast.innerHTML = `<i class="fas fa-exclamation-triangle me-2"></i>${msg}`;
          document.body.appendChild(errorToast);
          setTimeout(() => errorToast.remove(), 4000);
        }
      }
    } catch (error) {
      console.error('Failed to submit:', error);
      testApp.isSubmitting = false;
      const submitOverlayEl = document.getElementById('submit-overlay');
      if (submitOverlayEl) submitOverlayEl.style.display = 'none';

      const errorToast = document.createElement('div');
      errorToast.className = 'alert alert-danger position-fixed top-0 start-50 translate-middle-x mt-3';
      errorToast.style.zIndex = '9999';
      errorToast.innerHTML = '<i class="fas fa-exclamation-triangle me-2"></i>Failed to submit test. Please try again.';
      document.body.appendChild(errorToast);

      setTimeout(() => {
        errorToast.remove();
      }, 3000);

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
      OfflineQueue.saveAnswerSnapshot(UI.answers || {});

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

    // Offline / online detection
    window.addEventListener('offline', () => {
      testApp.isOffline = true;
      const banner = document.getElementById('offline-banner');
      if (banner) {
        banner.classList.add('visible');
        document.documentElement.style.setProperty('--offline-banner-height', banner.offsetHeight + 'px');
      }
    });

    window.addEventListener('online', () => {
      testApp.isOffline = false;
      const banner = document.getElementById('offline-banner');
      if (banner) {
        banner.classList.remove('visible');
        document.documentElement.style.setProperty('--offline-banner-height', '0px');
      }

      // Silently flush any answers that failed to save while offline
      OfflineQueue.flush();

      // Auto-submit if the submit was attempted while offline
      if (testApp.pendingSubmitOnReconnect) {
        testApp.pendingSubmitOnReconnect = false;
        const pendingToast = document.getElementById('pending-submit-toast');
        if (pendingToast) pendingToast.remove();
        testApp.submitAttempt();
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
