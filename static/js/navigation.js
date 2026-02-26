/**
 * Navigation Module
 * Handles prev/next question navigation
 */

const Navigation = {
  currentIndex: 0,
  totalQuestions: 0,

  // Initialize navigation
  init: (totalQuestions) => {
    Navigation.totalQuestions = totalQuestions;
    Navigation.currentIndex = 0;
    Navigation.updateButtons();
  },

  // Go to next question
  next: () => {
    if (Navigation.currentIndex < Navigation.totalQuestions - 1) {
      Navigation.currentIndex++;
      const nextQuestion = Palette.questions[Navigation.currentIndex];
      if (nextQuestion) {
        UI.selectQuestion(nextQuestion.id);
      }
    }
  },

  // Go to previous question
  prev: () => {
    if (Navigation.currentIndex > 0) {
      Navigation.currentIndex--;
      const prevQuestion = Palette.questions[Navigation.currentIndex];
      if (prevQuestion) {
        UI.selectQuestion(prevQuestion.id);
      }
    }
  },

  // Jump to specific question
  goTo: (questionId) => {
    const index = Palette.questions.findIndex(q => q.id === questionId);
    if (index !== -1) {
      Navigation.currentIndex = index;
    }
  },

  // Update button states
  updateButtons: () => {
    const prevBtn = document.getElementById('btn-prev');
    const nextBtn = document.getElementById('btn-next');

    if (prevBtn) {
      prevBtn.disabled = Navigation.currentIndex === 0;
    }
    if (nextBtn) {
      nextBtn.disabled = Navigation.currentIndex === Navigation.totalQuestions - 1;
    }
  },

  // Get current question index
  getCurrentIndex: () => {
    return Navigation.currentIndex;
  },

  // Get question at index
  getQuestionAt: (index) => {
    return Palette.questions[index];
  },
};
