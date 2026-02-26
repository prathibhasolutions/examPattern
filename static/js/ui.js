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
    } else {
      UI.answers[questionId].status = UI.answers[questionId].status || 'not_visited';
      if (UI.answers[questionId].status === 'not_visited') {
        UI.answers[questionId].status = 'visited';
        Palette.updateStatus(questionId, 'visited');
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
      html += `<img src="${question.image}" alt="Question" class="question-image">`;
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
        html += `<div style="margin-top: 0.75rem; margin-left: 2rem;"><img src="${option.image}" alt="Option image" class="option-image" style="max-width: 200px; border-radius: 0.25rem; box-shadow: 0 1px 4px rgba(0,0,0,0.1);"></div>`;
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
    // Option change
    document.querySelectorAll(`input[name="options"][data-question-id="${question.id}"]`).forEach(input => {
      input.addEventListener('change', () => {
        UI.onAnswerChange(question.id);
      });
      input.addEventListener('click', (e) => {
        const label = e.target.closest('.option');
        if (label) {
          label.classList.toggle('selected');
        }
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

    UI.answers[questionId] = answer;
    Palette.updateStatus(questionId, answer.status);

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
    UI.answers[questionId] = answer;
    Palette.updateStatus(questionId, answer.status);

    // Save immediately
    UI.saveAnswer(questionId);

    // Automatically go to next question
    Navigation.next();
  },

  // Debounced save (save after 2 seconds of inactivity)
  saveTimeout: null,
  debouncedSaveAnswer: (questionId) => {
    clearTimeout(UI.saveTimeout);
    UI.saveTimeout = setTimeout(() => {
      UI.saveAnswer(questionId);
    }, 2000);
  },

  // Save answer to backend
  saveAnswer: async (questionId) => {
    if (!ATTEMPT_ID) return;

    const answer = UI.answers[questionId];
    if (!answer) return;

    try {
      await API.saveAnswer(ATTEMPT_ID, {
        question: questionId,
        selected_option_ids: answer.selected_option_ids || [],
        response_text: answer.response_text || '',
        status: answer.status || 'visited',
        time_spent_seconds: answer.time_spent_seconds || 0,
      });
    } catch (error) {
      console.error('Failed to save answer:', error);
    }
  },

  // Escape HTML to prevent XSS
  escapeHtml: (text) => {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  },
};
