document.addEventListener('DOMContentLoaded', () => {
  const form = document.querySelector('[data-onboarding-form]');
  if (!(form instanceof HTMLFormElement)) return;
  const steps = Array.from(document.querySelectorAll('[data-onboarding-step]'));
  const stepTitle = document.querySelector('[data-onboarding-step-title]');
  const stepCounter = document.querySelector('[data-onboarding-step-counter]');
  const backBtn = document.querySelector('[data-onboarding-action="back"]');
  const nextBtn = document.querySelector('[data-onboarding-action="next"]');
  const submitBtn = document.querySelector('[data-onboarding-action="submit"]');
  const projectDetails = document.querySelector('[data-project-details]');
  const projectExperienceInputs = Array.from(form.querySelectorAll('input[name="has_project_experience"]'));
  const programmingKnowledge = form.querySelector('#programming_knowledge');
  const projectExamples = form.querySelector('#project_examples');
  const difficultyCheckboxes = Array.from(form.querySelectorAll('input[name="learning_difficulties"]'));
  const storageKey = 'nf-onboarding-draft';
  let currentStep = 0;
  function updateStepLabels() {
    if (stepTitle) {
      stepTitle.textContent = `Question ${currentStep + 1}`;
    }
    if (stepCounter) {
      stepCounter.textContent = `${currentStep + 1} of ${steps.length}`;
    }
    if (backBtn instanceof HTMLButtonElement) {
      backBtn.hidden = currentStep === 0;
    }
    if (nextBtn instanceof HTMLButtonElement) {
      nextBtn.hidden = currentStep === steps.length - 1;
    }
    if (submitBtn instanceof HTMLButtonElement) {
      submitBtn.hidden = currentStep !== steps.length - 1;
    }
  }
  function getSelectedProjectExperience() {
    const selected = projectExperienceInputs.find(input => input instanceof HTMLInputElement && input.checked);
    return selected instanceof HTMLInputElement ? selected.value : '';
  }
  function syncProjectDetailsVisibility() {
    const hasExperience = getSelectedProjectExperience() === 'yes';
    if (projectDetails instanceof HTMLElement) {
      projectDetails.hidden = !hasExperience;
    }
    if (projectExamples instanceof HTMLTextAreaElement) {
      projectExamples.required = hasExperience;
      if (!hasExperience) {
        projectExamples.value = '';
      }
    }
  }
  function syncLearningDifficultySelections() {
    const noneBox = difficultyCheckboxes.find(input => input instanceof HTMLInputElement && input.value === 'none');
    const selectedValues = difficultyCheckboxes
      .filter(input => input instanceof HTMLInputElement && input.checked)
      .map(input => input.value);
    if (noneBox instanceof HTMLInputElement && noneBox.checked && selectedValues.length > 1) {
      difficultyCheckboxes.forEach(input => {
        if (input instanceof HTMLInputElement && input !== noneBox) {
          input.checked = false;
        }
      });
    }
    if (noneBox instanceof HTMLInputElement && !noneBox.checked) {
      const otherChecked = difficultyCheckboxes.some(
        input => input instanceof HTMLInputElement && input.value !== 'none' && input.checked
      );
      if (otherChecked) {
        noneBox.checked = false;
      }
    }
  }
  function setStep(index) {
    const bounded = Math.max(0, Math.min(index, steps.length - 1));
    currentStep = bounded;
    steps.forEach((step, idx) => {
      step.hidden = idx !== bounded;
    });
    updateStepLabels();
    const focusTarget = steps[bounded]?.querySelector('select, input, textarea, button');
    if (focusTarget instanceof HTMLElement) {
      focusTarget.focus();
    }
  }
  function validateStep() {
    const step = steps[currentStep];
    if (!step) return true;
    const fields = Array.from(step.querySelectorAll('input, select, textarea'));
    for (const field of fields) {
      if (field instanceof HTMLInputElement && (field.type === 'radio' || field.type === 'checkbox')) {
        continue;
      }
      if (field instanceof HTMLElement && 'checkValidity' in field && !field.checkValidity()) {
        field.reportValidity();
        return false;
      }
    }
    // Validate required radio groups: ensure at least one option is selected.
    const radioNames = new Set(
      fields
        .filter(f => f instanceof HTMLInputElement && f.type === 'radio' && f.required)
        .map(f => /** @type {HTMLInputElement} */ (f).name)
    );
    for (const name of radioNames) {
      const group = /** @type {HTMLInputElement[]} */ (
        Array.from(step.querySelectorAll(`input[type="radio"][name="${CSS.escape(name)}"]`))
      );
      const anyChecked = group.some(r => r instanceof HTMLInputElement && r.checked);
      if (!anyChecked) {
        const first = group.find(r => r instanceof HTMLInputElement);
        if (first instanceof HTMLInputElement) {
          first.focus();
          first.setCustomValidity('Please select an option.');
          first.reportValidity();
          first.setCustomValidity('');
        }
        return false;
      }
    }
    if (currentStep === 1 && getSelectedProjectExperience() === 'yes') {
      if (projectExamples instanceof HTMLTextAreaElement && !projectExamples.value.trim()) {
        projectExamples.focus();
        projectExamples.reportValidity();
        return false;
      }
    }
    return true;
  }
  function serializeDraft() {
    const payload = {
      programming_knowledge: programmingKnowledge instanceof HTMLSelectElement ? programmingKnowledge.value : '',
      has_project_experience: getSelectedProjectExperience(),
      project_examples: projectExamples instanceof HTMLTextAreaElement ? projectExamples.value : '',
      learning_difficulties: difficultyCheckboxes
        .filter(input => input instanceof HTMLInputElement && input.checked)
        .map(input => input.value)
    };
    localStorage.setItem(storageKey, JSON.stringify(payload));
  }
  function restoreDraft() {
    const raw = localStorage.getItem(storageKey);
    if (!raw) return;
    try {
      const draft = JSON.parse(raw);
      if (programmingKnowledge instanceof HTMLSelectElement && typeof draft.programming_knowledge === 'string') {
        programmingKnowledge.value = draft.programming_knowledge;
      }
      if (typeof draft.has_project_experience === 'string') {
        const matching = projectExperienceInputs.find(
          input => input instanceof HTMLInputElement && input.value === draft.has_project_experience
        );
        if (matching instanceof HTMLInputElement) {
          matching.checked = true;
        }
      }
      if (projectExamples instanceof HTMLTextAreaElement && typeof draft.project_examples === 'string') {
        projectExamples.value = draft.project_examples;
      }
      if (Array.isArray(draft.learning_difficulties)) {
        difficultyCheckboxes.forEach(input => {
          if (!(input instanceof HTMLInputElement)) return;
          input.checked = draft.learning_difficulties.includes(input.value);
        });
      }
    } catch {
      localStorage.removeItem(storageKey);
    }
  }
  projectExperienceInputs.forEach(input => {
    input.addEventListener('change', () => {
      syncProjectDetailsVisibility();
      serializeDraft();
    });
  });
  difficultyCheckboxes.forEach(input => {
    input.addEventListener('change', () => {
      const noneBox = difficultyCheckboxes.find(box => box instanceof HTMLInputElement && box.value === 'none');
      if (!(input instanceof HTMLInputElement)) return;
      if (input.value === 'none' && input.checked) {
        difficultyCheckboxes.forEach(box => {
          if (box instanceof HTMLInputElement && box !== input) {
            box.checked = false;
          }
        });
      }
      if (input.value !== 'none' && input.checked && noneBox instanceof HTMLInputElement) {
        noneBox.checked = false;
      }
      serializeDraft();
    });
  });
  if (programmingKnowledge instanceof HTMLSelectElement) {
    programmingKnowledge.addEventListener('change', serializeDraft);
  }
  if (projectExamples instanceof HTMLTextAreaElement) {
    projectExamples.addEventListener('input', serializeDraft);
  }
  if (backBtn instanceof HTMLButtonElement) {
    backBtn.addEventListener('click', () => {
      if (currentStep > 0) setStep(currentStep - 1);
    });
  }
  if (nextBtn instanceof HTMLButtonElement) {
    nextBtn.addEventListener('click', () => {
      if (!validateStep()) return;
      serializeDraft();
      if (currentStep < steps.length - 1) setStep(currentStep + 1);
    });
  }
  form.addEventListener('submit', event => {
    syncProjectDetailsVisibility();
    syncLearningDifficultySelections();
    serializeDraft();
    if (!validateStep()) {
      event.preventDefault();
    }
  });
  restoreDraft();
  syncProjectDetailsVisibility();
  setStep(0);
});
