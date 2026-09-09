import {
  CheckCircleFilled,
  QuestionCircleOutlined,
} from "@ant-design/icons";
import { Button, Checkbox, Input, Radio, Tabs } from "antd";
import { useState } from "react";

import type {
  ChatAskUserQuestionRequestEvent,
  ChatPermissionAnswers,
} from "../bridge/client";

type AskUserQuestionDialogProps = {
  decision: "allow" | "deny" | null;
  onDecision: (
    allowed: boolean,
    answers?: ChatPermissionAnswers,
  ) => Promise<void>;
  request: ChatAskUserQuestionRequestEvent;
};

type AnswerDraft = {
  custom: string;
  selected: string[];
};

function isAnswered(draft: AnswerDraft): boolean {
  return draft.selected.length > 0 || Boolean(draft.custom.trim());
}

export function AskUserQuestionDialog({
  decision,
  onDecision,
  request,
}: AskUserQuestionDialogProps) {
  const questions = request.input.questions;
  const [activeKey, setActiveKey] = useState("0");
  const [drafts, setDrafts] = useState<AnswerDraft[]>(() => (
    questions.map(() => ({ custom: "", selected: [] }))
  ));
  const [validationError, setValidationError] = useState("");
  const answeredCount = drafts.filter(isAnswered).length;
  const activeIndex = Number(activeKey);
  const isLastQuestion = activeIndex === questions.length - 1;

  const updateDraft = (index: number, next: Partial<AnswerDraft>) => {
    setDrafts((current) => current.map((draft, draftIndex) => (
      draftIndex === index ? { ...draft, ...next } : draft
    )));
    setValidationError("");
  };

  const submitAnswers = async () => {
    const firstUnanswered = drafts.findIndex((draft) => !isAnswered(draft));
    if (firstUnanswered >= 0) {
      setActiveKey(String(firstUnanswered));
      setValidationError(`请先回答“${questions[firstUnanswered].header || `问题 ${firstUnanswered + 1}`}”。`);
      return;
    }

    const answers: ChatPermissionAnswers = {};
    questions.forEach((question, index) => {
      const draft = drafts[index];
      const custom = draft.custom.trim();
      answers[question.question] = question.multiSelect
        ? [...draft.selected, ...(custom ? [custom] : [])]
        : custom || draft.selected[0];
    });
    await onDecision(true, answers);
  };

  const goToNextQuestion = () => {
    if (!isAnswered(drafts[activeIndex])) {
      setValidationError("请先回答当前问题，再进入下一步。");
      return;
    }
    setActiveKey(String(activeIndex + 1));
    setValidationError("");
  };

  const renderQuestion = (index: number) => {
    const question = questions[index];
    const draft = drafts[index];
    return (
      <div className="ask-question-scroll">
        <div className="ask-question-pane">
          <strong className="ask-question-title">{question.question}</strong>
          {question.multiSelect ? (
            <Checkbox.Group
              className="ask-question-options"
              disabled={decision !== null}
              onChange={(values) => updateDraft(index, {
                selected: values.map(String),
              })}
              value={draft.selected}
            >
              {question.options.map((option) => (
                <Checkbox
                  className="ask-question-option"
                  key={option.label}
                  value={option.label}
                >
                  <span className="ask-question-option-copy">
                    <strong>{option.label}</strong>
                    {option.description && <small>{option.description}</small>}
                  </span>
                </Checkbox>
              ))}
            </Checkbox.Group>
          ) : (
            <Radio.Group
              className="ask-question-options"
              disabled={decision !== null}
              onChange={(event) => updateDraft(index, {
                custom: "",
                selected: [String(event.target.value)],
              })}
              value={draft.selected[0]}
            >
              {question.options.map((option) => (
                <Radio
                  className="ask-question-option"
                  key={option.label}
                  value={option.label}
                >
                  <span className="ask-question-option-copy">
                    <strong>{option.label}</strong>
                    {option.description && <small>{option.description}</small>}
                  </span>
                </Radio>
              ))}
            </Radio.Group>
          )}
          <Input.TextArea
            aria-label={`自定义回答：${question.question}`}
            autoSize={{ minRows: 1, maxRows: 3 }}
            disabled={decision !== null}
            onChange={(event) => updateDraft(index, {
              custom: event.target.value,
              ...(!question.multiSelect && event.target.value.trim()
                ? { selected: [] }
                : {}),
            })}
            placeholder={question.multiSelect ? "补充其他答案（可选）" : "或者输入其他答案"}
            value={draft.custom}
          />
        </div>
      </div>
    );
  };

  const items = questions.map((question, index) => {
    const answered = isAnswered(drafts[index]);
    return {
      key: String(index),
      label: (
        <span className="ask-question-tab-label">
          <span>{question.header || `问题 ${index + 1}`}</span>
          {answered && <CheckCircleFilled aria-label="已回答" />}
        </span>
      ),
      children: renderQuestion(index),
    };
  });

  return (
    <section
      aria-labelledby={`ask-user-question-title-${request.permission_id}`}
      aria-modal="true"
      className="tool-permission-dialog ask-user-question-dialog"
      role="dialog"
    >
      <div className="tool-permission-heading">
        <span className="tool-permission-icon"><QuestionCircleOutlined /></span>
        <div className="tool-permission-copy">
          <strong id={`ask-user-question-title-${request.permission_id}`}>
            Claude 需要你的回答
          </strong>
          <span>回答完成后，Claude 会继续当前任务。</span>
        </div>
        <code>{answeredCount}/{questions.length}</code>
      </div>
      <Tabs
        activeKey={activeKey}
        animated={{ inkBar: true, tabPane: true }}
        className="ask-question-tabs"
        destroyOnHidden={false}
        items={items}
        onChange={(key) => {
          setActiveKey(key);
          setValidationError("");
        }}
        size="small"
      />
      <div className="ask-question-footer">
        <span aria-live="polite" className="ask-question-validation">
          {validationError}
        </span>
        <div className="tool-permission-actions">
          {isLastQuestion ? (
            <>
              <Button
                danger
                disabled={decision !== null}
                loading={decision === "deny"}
                onClick={() => void onDecision(false)}
              >
                取消
              </Button>
              <Button
                disabled={decision !== null}
                loading={decision === "allow"}
                onClick={() => void submitAnswers()}
                type="primary"
              >
                提交回答
              </Button>
            </>
          ) : (
            <Button
              disabled={decision !== null}
              onClick={goToNextQuestion}
              type="primary"
            >
              下一步
            </Button>
          )}
        </div>
      </div>
    </section>
  );
}
