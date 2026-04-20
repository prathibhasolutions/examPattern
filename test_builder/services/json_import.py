import json

from django.db import transaction

from test_builder.models import OptionDraft, QuestionDraft


@transaction.atomic
def import_json_into_section(section, json_text: str) -> dict:
    """
    Parse a JSON array of questions and import them as QuestionDraft / OptionDraft records.

    Expected input format:
    [
      {
        "question_text": "...",
        "solution_text": "",
        "options": [
          {"option_text": "...", "is_correct": true},
          {"option_text": "...", "is_correct": false},
          ...
        ]
      },
      ...
    ]

    Returns:
        {
            "imported_count": int,
            "skipped_count": int,
            "skip_summary": list[str],
        }
    """
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc}") from exc

    if not isinstance(data, list):
        raise ValueError("JSON must be an array (list) of question objects.")

    base_order = section.questions.count()
    imported_count = 0
    skipped_count = 0
    skip_summary = []

    for i, item in enumerate(data):
        q_num = i + 1

        if not isinstance(item, dict):
            skipped_count += 1
            skip_summary.append(f"Q{q_num}: not an object")
            continue

        question_text = (item.get("question_text") or "").strip()
        solution_text = (item.get("solution_text") or "").strip()
        options_data = item.get("options") or []

        if not question_text:
            skipped_count += 1
            skip_summary.append(f"Q{q_num}: missing question_text")
            continue

        if not isinstance(options_data, list) or len(options_data) < 2:
            skipped_count += 1
            skip_summary.append(f"Q{q_num}: needs at least 2 options")
            continue

        correct_count = sum(1 for opt in options_data if opt.get("is_correct"))
        if correct_count != 1:
            skipped_count += 1
            skip_summary.append(
                f"Q{q_num}: must have exactly 1 correct option (found {correct_count})"
            )
            continue

        # Validate every option has text
        bad_option = False
        for j, opt in enumerate(options_data):
            if not isinstance(opt, dict) or not (opt.get("option_text") or "").strip():
                skipped_count += 1
                skip_summary.append(f"Q{q_num} option {j + 1}: missing option_text")
                bad_option = True
                break
        if bad_option:
            continue

        question = QuestionDraft.objects.create(
            section=section,
            question_text=question_text,
            solution_text=solution_text,
            order=base_order + imported_count + 1,
            is_bonus=False,
        )

        for j, opt in enumerate(options_data):
            OptionDraft.objects.create(
                question=question,
                option_text=opt["option_text"].strip(),
                is_correct=bool(opt.get("is_correct")),
                order=j + 1,
            )

        imported_count += 1

    return {
        "imported_count": imported_count,
        "skipped_count": skipped_count,
        "skip_summary": skip_summary,
    }
