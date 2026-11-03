import request from "./request";

const ROOT = "/api/v1/answer-corrections/";

export interface CorrectionFeedback {
    id: number;
    quote: string;
    state: "pending_assignment" | "pending_processing" | "pending_reply" | "replied";
    reply: string | null;
}

interface FeedbackDraft {
    answer_id: number;
    quote: string;
    correction: string;
    evidence: string;
}

interface FeedbackResponse<T> {
    status_code: number;
    data: T;
}

function unwrap<T>(response: FeedbackResponse<T>): T {
    if (response.status_code !== 200) throw new Error("Feedback request failed");
    return response.data;
}

export async function getCorrectionEligibility(answerId: number) {
    return unwrap(await request.get<FeedbackResponse<{ eligible: boolean }>>(
        `${ROOT}eligibility/${answerId}`, { showError: false },
    ));
}

export async function submitCorrection(draft: FeedbackDraft): Promise<CorrectionFeedback> {
    const response: FeedbackResponse<CorrectionFeedback> = await request.post(ROOT, draft);
    return unwrap(response);
}

export async function listMyCorrections(page: number) {
    return unwrap(await request.get<FeedbackResponse<{ items: CorrectionFeedback[]; total: number }>>(ROOT, {
        params: { view: "mine", page },
    }));
}
