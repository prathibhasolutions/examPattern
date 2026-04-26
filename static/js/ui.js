/**
 * UI Module
 * Handles rendering questions and managing UI state
 */

const UI = {
  answers: {}, // Cached answers: { questionId: answerData }
  currentQuestion: null,

  // Initialize answers from attempt
  initAnswers: (attemptAnswers) => {
    attemptAnswers.forEach(answer => {
      UI.answers[answer.question] = {
        ...answer,
        status: answer.status || 'not_visited',
        selected_option_ids: answer.selected_option_ids || [],
        timeSpentSeconds: answer.time_spent_seconds,
        _savedToServer: true,  // loaded from server — already clean
        _saveSeq: 0,
      };
    });
  },

  // Select and display a question
  selectQuestion: (questionId) => {
    const question = Palette.getQuestion(questionId);
    if (!question) return;

    if (window.testApp && typeof window.testApp.canNavigateToQuestion === 'function') {
      const allowed = window.testApp.canNavigateToQuestion(questionId);
      if (!allowed) {
        return;
      }
    }

    UI.currentQuestion = question;
    if (window.testApp && typeof window.testApp.handleSectionChange === 'function') {
      window.testApp.handleSectionChange(question.section_id);
    }
    
    // Update section tab and question number
    if (window.testApp && typeof window.testApp.updateActiveSectionTab === 'function') {
      window.testApp.updateActiveSectionTab(question.section_id);
    }
    if (window.testApp && typeof window.testApp.updateQuestionNumber === 'function') {
      window.testApp.updateQuestionNumber(questionId);
    }
    
    Navigation.goTo(questionId);
    Navigation.updateButtons();
    Palette.setActive(questionId);

    // Start time tracking for this question
    if (window.TimeTracker && typeof window.TimeTracker.startTracking === 'function') {
      window.TimeTracker.startTracking(questionId);
    }

    // Mark as visited if not already
    if (!UI.answers[questionId]) {
      UI.answers[questionId] = {
        question: questionId,
        status: 'visited',
        selected_option_ids: [],
        response_text: '',
        time_spent_seconds: 0,
        marks_obtained: null,
      };
      Palette.updateStatus(questionId, 'visited');
      UI.saveAnswer(questionId);
    } else {
      UI.answers[questionId].status = UI.answers[questionId].status || 'not_visited';
      if (UI.answers[questionId].status === 'not_visited') {
        UI.answers[questionId].status = 'visited';
        Palette.updateStatus(questionId, 'visited');
        UI.saveAnswer(questionId);
      }
    }

    UI.renderQuestion(question);
  },

  // Render question content
  renderQuestion: (question) => {
    const container = document.getElementById('question-container');
    if (!container) return;

    const answer = UI.answers[question.id] || {};
    let html = `<div class="question-wrapper">`;

    // Question text - use extracted_text if available, otherwise use regular text
    const displayText = question.extracted_text || question.text;
    if (displayText) {
      const textClass = question.is_math ? 'math-text' : '';
      html += `<div class="question-text ${textClass}">${UI.escapeHtml(displayText)}</div>`;
    }

    // Question image
    if (question.image) {
      html += `<img src="${question.image}" alt="Question" class="question-image" loading="lazy">`;
    }

    // Options or text area based on question type
    if (question.options && question.options.length > 0) {
      html += UI.renderOptions(question, answer);
    } else {
      html += UI.renderTextResponse(question, answer);
    }

    html += '</div>';
    container.innerHTML = html;

    // Attach event listeners
    UI.attachEventListeners(question);
    
    // Trigger MathJax rendering for mathematical content
    if (window.MathJax) {
      MathJax.typesetPromise([container]).catch(err => console.error('MathJax error:', err));
    }
  },

  // Render options (MCQ/MCA)
  renderOptions: (question, answer) => {
    let html = '<div class="option-group">';
    const isMultiple = question.options.filter(o => o.is_correct).length > 1;
    const inputType = isMultiple ? 'checkbox' : 'radio';

    question.options.forEach(option => {
      const optionId = `option-${option.id}`;
      const isSelected = answer.selected_option_ids && answer.selected_option_ids.includes(option.id);
      const selectedClass = isSelected ? 'selected' : '';

      html += `
        <label class="option ${selectedClass}">
          <input type="${inputType}" name="options" id="${optionId}" value="${option.id}"
            data-question-id="${question.id}" ${isSelected ? 'checked' : ''}>
      `;

      if (option.text) {
        html += `<span>${UI.escapeHtml(option.text)}</span>`;
      }

      if (option.image) {
        html += `<div style="margin-top: 0.75rem; margin-left: 2rem;"><img src="${option.image}" alt="Option image" class="option-image" loading="lazy" style="max-width: 200px; border-radius: 0.25rem; box-shadow: 0 1px 4px rgba(0,0,0,0.1);"></div>`;
      }

      html += '</label>';
    });

    html += '</div>';
    return html;
  },

  // Render text response (subjective)
  renderTextResponse: (question, answer) => {
    return `
      <textarea id="response-${question.id}" class="form-control response-text" 
        placeholder="Enter your response...">${UI.escapeHtml(answer.response_text || '')}</textarea>
    `;
  },

  // Attach event listeners to question inputs
  attachEventListeners: (question) => {
    // Option change: drive CSS from actual checked state, then save
    document.querySelectorAll(`input[name="options"][data-question-id="${question.id}"]`).forEach(input => {
      input.addEventListener('change', () => {
        // Update 'selected' class on every option label based on real checked state
        document.querySelectorAll(`input[name="options"][data-question-id="${question.id}"]`).forEach(opt => {
          const lbl = opt.closest('.option');
          if (lbl) lbl.classList.toggle('selected', opt.checked);
        });
        UI.onAnswerChange(question.id);
      });
    });

    // Text response
    const textArea = document.getElementById(`response-${question.id}`);
    if (textArea) {
      textArea.addEventListener('input', () => {
        UI.onAnswerChange(question.id);
      });
    }
  },

  // Called when answer changes
  onAnswerChange: (questionId) => {
    const answer = UI.answers[questionId] || {};

    // Collect selected options
    const selectedOptions = Array.from(
      document.querySelectorAll(`input[name="options"][data-question-id="${questionId}"]:checked`)
    ).map(el => parseInt(el.value));

    // Collect text response
    const textArea = document.getElementById(`response-${questionId}`);
    const responseText = textArea ? textArea.value : '';

    // Update answer
    answer.selected_option_ids = selectedOptions;
    answer.response_text = responseText;

    // Determine status (preserve marked status if already marked)
    const hasAnswer = selectedOptions.length > 0 || responseText.trim().length > 0;
    const wasMarked = answer.status === 'marked_for_review' || answer.status === 'answered_and_marked';
    
    if (hasAnswer) {
      answer.status = wasMarked ? 'answered_and_marked' : 'answered';
    } else if (wasMarked) {
      answer.status = 'marked_for_review';
    } else {
      answer.status = 'visited';
    }

    // Mark dirty: increment sequence so any in-flight "visited" save that
    // completes after this point will NOT overwrite _savedToServer back to true.
    answer._saveSeq = (answer._saveSeq || 0) + 1;
    answer._savedToServer = false;
    UI.answers[questionId] = answer;
    Palette.updateStatus(questionId, answer.status);
    if (window.OfflineQueue && typeof window.OfflineQueue.saveAnswerSnapshot === 'function') {
      window.OfflineQueue.saveAnswerSnapshot(UI.answers);
    }

    // Debounce auto-save
    UI.debouncedSaveAnswer(questionId);
  },

  // Mark current question for review
  markForReview: () => {
    if (!UI.currentQuestion) return;

    const questionId = UI.currentQuestion.id;
    const answer = UI.answers[questionId] || {};

    // Collect current answer state
    const selectedOptions = Array.from(
      document.querySelectorAll(`input[name="options"][data-question-id="${questionId}"]:checked`)
    ).map(el => parseInt(el.value));

    const textArea = document.getElementById(`response-${questionId}`);
    const responseText = textArea ? textArea.value : '';
    const hasAnswer = selectedOptions.length > 0 || responseText.trim().length > 0;

    // Toggle marked status
    const isCurrentlyMarked = answer.status === 'marked_for_review' || answer.status === 'answered_and_marked';
    
    if (hasAnswer) {
      answer.status = isCurrentlyMarked ? 'answered' : 'answered_and_marked';
    } else {
      answer.status = isCurrentlyMarked ? 'visited' : 'marked_for_review';
    }

    answer.selected_option_ids = selectedOptions;
    answer.response_text = responseText;
    answer._saveSeq = (answer._saveSeq || 0) + 1;
    answer._savedToServer = false;
    UI.answers[questionId] = answer;
    Palette.updateStatus(questionId, answer.status);
    if (window.OfflineQueue && typeof window.OfflineQueue.saveAnswerSnapshot === 'function') {
      window.OfflineQueue.saveAnswerSnapshot(UI.answers);
    }

    // Save immediately
    UI.saveAnswer(questionId);

    // Automatically go to next question
    Navigation.next();
  },

  // Debounced save (save after 2 seconds of inactivity per question)
  // Uses a per-question timeout map so navigating to Q2 never cancels Q1's save.
  saveTimeouts: {},
  debouncedSaveAnswer: (questionId) => {
    clearTimeout(UI.saveTimeouts[questionId]);
    UI.saveTimeouts[questionId] = setTimeout(() => {
      delete UI.saveTimeouts[questionId];
      UI.saveAnswer(questionId);
    }, 2000);
  },

  // Save answer to backend
  saveAnswer: async (questionId) => {
    if (!ATTEMPT_ID) return;

    const answer = UI.answers[questionId];
    if (!answer) return;

    // Capture the sequence number BEFORE the async fetch so we can detect
    // whether the answer was dirtied again while the request was in flight.
    const seqAtSend = answer._saveSeq || 0;

    const payload = {
      question: questionId,
      selected_option_ids: answer.selected_option_ids || [],
      response_text: answer.response_text || '',
      status: answer.status || 'visited',
      time_spent_seconds: answer.time_spent_seconds || 0,
    };

    try {
      await API.saveAnswer(ATTEMPT_ID, payload);
      // Only mark clean if no newer mutation arrived while we were waiting.
      // If _saveSeq advanced, onAnswerChange already set _savedToServer=false
      // and we must NOT override that back to true.
      if (UI.answers[questionId] && (UI.answers[questionId]._saveSeq || 0) === seqAtSend) {
        UI.answers[questionId]._savedToServer = true;
      }
    } catch (error) {
      console.error('Failed to save answer:', error);
      // Queue for retry when internet returns
      if (window.OfflineQueue) {
        OfflineQueue.enqueue(questionId, payload);
      }
    }
  },

  // Clear current question's response
  clearResponse: () => {
    if (!UI.currentQuestion) return;

    const questionId = UI.currentQuestion.id;
    const answer = UI.answers[questionId] || {};

    // Uncheck all inputs and remove selected class from labels
    document.querySelectorAll(`input[name="options"][data-question-id="${questionId}"]`).forEach(input => {
      input.checked = false;
      const label = input.closest('.option');
      if (label) label.classList.remove('selected');
    });

    // Clear text area if present
    const textArea = document.getElementById(`response-${questionId}`);
    if (textArea) textArea.value = '';

    // Update answer state — preserve marked status but remove answered
    answer.selected_option_ids = [];
    answer.response_text = '';
    const wasMarked = answer.status === 'marked_for_review' || answer.status === 'answered_and_marked';
    answer.status = wasMarked ? 'marked_for_review' : 'visited';
    answer._saveSeq = (answer._saveSeq || 0) + 1;
    answer._savedToServer = false;

    UI.answers[questionId] = answer;
    Palette.updateStatus(questionId, answer.status);
    if (window.OfflineQueue && typeof window.OfflineQueue.saveAnswerSnapshot === 'function') {
      window.OfflineQueue.saveAnswerSnapshot(UI.answers);
    }

    // Save cleared state to backend immediately
    UI.saveAnswer(questionId);
  },

  // Escape HTML to prevent XSS
  escapeHtml: (text) => {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  },
};
