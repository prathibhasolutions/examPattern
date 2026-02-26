/**
 * Palette Module
 * Question palette sidebar with status indicators
 */

const Palette = {
  questions: [],
  sections: [],
  currentQuestionId: null,

  // Initialize palette with questions
  init: (questions, sections = []) => {
    Palette.questions = questions;
    Palette.sections = sections;
    // Don't auto-render if sections exist - will be filtered on first question load
    if (sections.length === 0) {
      Palette.render();
    }
  },

  // Render palette
  render: (filterSectionId = null) => {
    const paletteEl = document.getElementById('palette');
    if (!paletteEl) return;

    paletteEl.innerHTML = '';

    // Get questions for the specified section or all
    const questionsToShow = filterSectionId 
      ? Palette.questions.filter(q => q.section_id === filterSectionId)
      : Palette.questions;

    questionsToShow
      .sort((a, b) => (a.question_number || 0) - (b.question_number || 0))
      .forEach(q => {
        const btn = document.createElement('button');
        btn.className = 'question-item';
        btn.id = `q-btn-${q.id}`;
        btn.textContent = `${q.question_number || ''}`;
        btn.dataset.questionId = q.id;

        Palette.applyStatusClass(btn, q.status);

        btn.addEventListener('click', () => {
          UI.selectQuestion(q.id);
        });

        paletteEl.appendChild(btn);
      });
  },

  // Update palette to show only questions from a specific section
  filterBySection: (sectionId) => {
    Palette.render(sectionId);
  },

  // Update question status in palette
  updateStatus: (questionId, newStatus) => {
    const question = Palette.questions.find(q => q.id === questionId);
    if (question) {
      question.status = newStatus;
      const btn = document.getElementById(`q-btn-${questionId}`);
      if (btn) {
        Palette.applyStatusClass(btn, newStatus);
      }
    }
  },

  // Apply status color class
  applyStatusClass: (element, status) => {
    element.classList.remove('not-visited', 'visited', 'answered', 'marked-for-review', 'answered-and-marked');
    
    const classMap = {
      'not_visited': 'not-visited',
      'visited': 'visited',
      'answered': 'answered',
      'marked_for_review': 'marked-for-review',
      'answered_and_marked': 'answered-and-marked',
    };

    const className = classMap[status] || 'not-visited';
    element.classList.add(className);
  },

  // Get question by ID
  getQuestion: (questionId) => {
    return Palette.questions.find(q => q.id === questionId);
  },

  // Set active question in palette
  setActive: (questionId) => {
    document.querySelectorAll('.question-item').forEach(btn => {
      btn.classList.remove('active');
    });
    const activeBtn = document.getElementById(`q-btn-${questionId}`);
    if (activeBtn) {
      activeBtn.classList.add('active');
    }
  },

  // Get all question statuses
  getStatuses: () => {
    const statuses = {};
    Palette.questions.forEach(q => {
      statuses[q.id] = q.status;
    });
    return statuses;
  },
};
