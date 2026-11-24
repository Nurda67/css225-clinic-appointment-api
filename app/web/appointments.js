import {
    badge, button, clinicDay, detailList, element, empty, formDialog,
    formatDateTime, formatDay, formatTime, openDialog, runAction, section,
} from "./ui.js";

const tones = {
    booked: ["Booked", "blue"], done: ["Completed", "green"], no_show: ["No-Show", "red"],
    cancelled: ["Cancelled", ""], waiting: ["Waiting", "amber"], offered: ["Offered", "blue"],
    expired: ["Expired", ""], pending: ["Pending", "amber"], accepted: ["Accepted", "green"],
    stale: ["Unavailable", ""], approved: ["Approved", "green"], published: ["Published", "green"],
};

function statusBadge(status) {
    const [title, tone] = tones[status] || ["Unknown", ""];
    return badge(title, tone);
}

function readAction(label, action) {
    return button(label, (control) => runAction(control, action));
}

function saveAction(label, context, path, method, body, message, variant = "") {
    return button(label, (control) => runAction(control, () => context.save(path, {method, body}, message)), variant);
}

async function getIntake(context, id) {
    try {
        return await context.request(`/appointments/${id}/intake`);
    } catch (error) {
        if (error.status === 404) return null;
        throw error;
    }
}

async function editIntake(context, id) {
    const intake = await getIntake(context, id);
    formDialog("Intake Form", [
        {name: "reason", label: "Reason for the Visit", type: "textarea", maxLength: 500, value: intake?.reason},
        {name: "questions", label: "Questions for the Doctor", type: "textarea", required: false, maxLength: 1000, value: intake?.questions},
    ], "Save Intake Form", (body) => context.save(`/appointments/${id}/intake`, {method: "PUT", body}, "Intake form saved."));
}

async function viewIntake(context, id) {
    const intake = await getIntake(context, id);
    const content = intake
        ? detailList([["Reason for the Visit", intake.reason], ["Questions for the Doctor", intake.questions]])
        : empty("This patient has not submitted an intake form.");
    openDialog("Intake Form", content);
}

function cancelAppointment(context, appointment) {
    const content = element("div", "", "stack");
    content.append(
        element("p", `Cancel the appointment with ${context.doctorName(appointment.doctor_id)} on ${formatDateTime(appointment.starts_at)}?`),
        saveAction("Confirm Cancellation", context, `/appointments/${appointment.id}`, "PATCH", {status: "cancelled"}, "Appointment cancelled.", "danger"),
    );
    openDialog("Cancel Appointment", content);
}

function leaveReview(context, id) {
    formDialog("Review Your Appointment", [
        {name: "rating", label: "Rating", options: [5, 4, 3, 2, 1].map((score) => ({value: score, label: `${score} / 5`}))},
        {name: "comment", label: "Comment", type: "textarea", required: false, maxLength: 1000},
    ], "Submit Review", ({rating, comment}) => context.save(
        `/appointments/${id}/review`, {method: "POST", body: {rating: Number(rating), comment}},
        "Review submitted for moderation.",
    ));
}

function completeVisit(context, id) {
    formDialog("Complete Visit", [
        {name: "diagnosis", label: "Consultation Result", type: "textarea", maxLength: 500},
        {name: "notes", label: "Notes", type: "textarea", required: false, maxLength: 2000},
    ], "Save and Complete Visit", (body) => context.save(
        `/appointments/${id}/medical-record`, {method: "POST", body},
        "Visit completed. The result was saved to the patient's history.",
    ));
}

function markNoShow(context, id) {
    const content = element("div", "", "stack");
    content.append(element("p", "Confirm that the patient did not attend this appointment."),
        saveAction("Confirm No-Show", context, `/appointments/${id}/attendance`, "PATCH", {status: "no_show"}, "Appointment marked No-Show.", "danger"));
    openDialog("Mark No-Show", content);
}

function recommendFollowUp(context, id) {
    const today = clinicDay();
    formDialog("Recommend a Follow-Up", [
        {name: "start_date", label: "First Day", type: "date", min: today, value: clinicDay(7)},
        {name: "end_date", label: "Last Day", type: "date", min: today, value: clinicDay(13)},
    ], "Send Recommendation", (body) => context.save(
        `/appointments/${id}/follow-up`, {method: "POST", body}, "Follow-up recommendation sent to the patient.",
    ));
}

async function editWorkingHours(context) {
    const schedule = await context.request("/doctors/me/schedule");
    const choices = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
    formDialog("Set Working Hours", [
        {name: "weekday", label: "Day of the Week", options: choices.map((label, value) => ({value, label}))},
        {name: "start", label: "Start Time", type: "time", value: "09:00"},
        {name: "end", label: "End Time", type: "time", value: "17:00"},
        {name: "slot_minutes", label: "Slot Length in Minutes", type: "number", min: 5, max: 120, value: 30},
    ], "Save Working Hours", ({weekday, start, end, slot_minutes}) => context.save(
        `/doctors/me/schedule/${weekday}`, {method: "PUT", body: {start, end, slot_minutes: Number(slot_minutes)}},
        "Working hours updated.",
    ), (inputs) => {
        function selectDay() {
            const hours = schedule.schedule.find((row) => row.weekday === Number(inputs.weekday.value));
            inputs.start.value = hours?.start.slice(0, 5) || "09:00";
            inputs.end.value = hours?.end.slice(0, 5) || "17:00";
            inputs.slot_minutes.value = hours?.slot_minutes || 30;
        }
        inputs.weekday.addEventListener("change", selectDay);
        selectDay();
    });
}

function appointmentCard(appointment, context, detail) {
    const {id, status, starts_at, ends_at, arrived_at, doctor_id, patient_id, previous_appointment_id} = appointment;
    const isDoctor = context.user.role === "doctor";
    const card = element("article", "", "card");
    const heading = element("div", "", "card-top");
    const title = isDoctor ? `Patient ${patient_id}` : context.doctorName(doctor_id);
    const shownStatus = status === "booked" && arrived_at ? badge("Arrived", "green") : statusBadge(status);
    heading.append(element("h3", title), shownStatus);
    card.append(heading, element("p", `${formatDateTime(starts_at)} to ${formatTime(ends_at)}`, "muted"));
    const actions = element("div", "", "actions");
    const started = Date.parse(starts_at) <= Date.now();

    if (!isDoctor && status === "booked" && !started) {
        actions.append(
            button("Reschedule", () => context.chooseSlot({
                title: "Reschedule Appointment", doctorId: doctor_id, actionLabel: "Reschedule Appointment",
                path: `/appointments/${id}/reschedule`, method: "PATCH", success: "Appointment rescheduled.",
            }), "primary"),
            readAction("Fill Intake Form", () => editIntake(context, id)),
            button("Cancel Appointment", () => cancelAppointment(context, appointment), "danger"),
        );
    }
    if (isDoctor && status === "booked") {
        actions.append(readAction("View Intake Form", () => viewIntake(context, id)));
        if (started && !arrived_at) {
            actions.append(
                saveAction("Mark Arrived", context, `/appointments/${id}/attendance`, "PATCH", {status: "arrived"}, "Patient marked Arrived.", "primary"),
                button("Mark No-Show", () => markNoShow(context, id), "danger"),
            );
        }
        if (arrived_at) actions.append(button("Complete Visit", () => completeVisit(context, id), "primary"));
    }
    if (status === "done") {
        actions.append(readAction("View Consultation", () => context.showConsultation(id)));
        if (isDoctor) {
            actions.append(readAction("View Intake Form", () => viewIntake(context, id)));
            if (!detail.recommendations.has(id)) actions.append(button("Recommend Follow-Up", () => recommendFollowUp(context, id), "primary"));
        } else {
            const review = detail.reviews.get(id);
            const certificate = detail.certificates.get(id);
            if (!review) actions.append(button("Leave a Review", () => leaveReview(context, id)));
            else actions.append(badge(review.status === "published" ? "Review Published" : "Review Pending", review.status === "published" ? "green" : "amber"));
            if (!certificate) actions.append(saveAction(
                "Request Proof of Attendance", context, `/appointments/${id}/certificate`, "POST", null,
                "Proof of attendance requested.",
            ));
            else if (certificate.status === "approved") actions.append(readAction("Download PDF", () => context.downloadCertificate(id)));
            else actions.append(badge("Certificate Pending", "amber"));
        }
    }
    if (previous_appointment_id && status !== "no_show" && (!isDoctor || detail.ownVisits.has(previous_appointment_id))) {
        actions.append(readAction("View Previous Consultation", () => context.showConsultation(previous_appointment_id)));
    }
    if (actions.childElementCount) card.append(actions);
    return card;
}

function rows(items, render, emptyLabel) {
    const list = element("div", "", "stack");
    for (const item of items) list.append(render(item));
    return items.length ? list : empty(emptyLabel);
}

export async function renderAppointments(body, context) {
    const isDoctor = context.user.role === "doctor";
    const [appointments, , reviews, certificates, recommendations] = await Promise.all([
        context.request("/appointments"), context.loadDoctors(),
        isDoctor ? [] : context.request("/reviews/me"),
        isDoctor ? [] : context.request("/certificates"),
        isDoctor ? context.request("/follow-ups") : [],
    ]);
    const detail = {
        reviews: new Map(reviews.map((row) => [row.appointment_id, row])),
        certificates: new Map(certificates.map((row) => [row.appointment_id, row])),
        recommendations: new Set(recommendations.map((row) => row.original_appointment_id)),
        ownVisits: new Set(appointments.map((row) => row.id)),
    };
    const open = appointments.filter((row) => row.status === "booked");
    const closed = appointments.filter((row) => row.status !== "booked").reverse();
    const render = (item) => appointmentCard(item, context, detail);
    body.replaceChildren();
    if (isDoctor) {
        const toolbar = element("div", "", "actions");
        toolbar.append(readAction("Set Working Hours", () => editWorkingHours(context)));
        body.append(toolbar);
    }
    body.append(section("Open Appointments", rows(open, render, "No open appointments.")),
        section("Visit History", rows(closed, render, "No visits in your history.")));
}

function waitlistStatus(item) {
    if (item.status === "waiting" && item.day < clinicDay()) return "expired";
    if (item.status === "offered" && Date.parse(item.offered_start) <= Date.now()) return "expired";
    return item.status;
}

function waitlistAction(context, item) {
    if (item.status !== "offered" || !item.offered_start || Date.parse(item.offered_start) <= Date.now()) return null;
    return saveAction("Accept Slot", context, `/waitlist/${item.id}/accept`, "POST", null, "Waitlist slot booked.", "primary");
}

function chooseFollowUp(context, item) {
    if (item.booked_appointment_id || item.end_date < clinicDay()) return null;
    return button("Choose Time", () => context.chooseSlot({
        title: "Book a Follow-Up", doctorId: item.doctor_id, actionLabel: "Book Follow-Up",
        path: `/follow-ups/${item.id}/book`, firstDay: item.start_date, lastDay: item.end_date,
        success: "Follow-up booked. The previous consultation is linked.",
    }), "primary");
}

function replacementAction(context, item) {
    if (item.status !== "pending" || Date.parse(item.starts_at) <= Date.now()) return null;
    return saveAction("Confirm Replacement", context, `/shift-replacements/${item.id}/accept`, "POST", null, "Replacement confirmed. Your appointment time is unchanged.", "primary");
}

function requestCard(title, description, state, action) {
    const card = element("article", "", "card");
    const heading = element("div", "", "card-top");
    heading.append(element("h3", title), state);
    card.append(heading, element("p", description, "muted"));
    if (action) {
        const actions = element("div", "", "actions");
        actions.append(action);
        card.append(actions);
    }
    return card;
}

export async function renderRequests(body, context) {
    const [waitlist, followUps, replacements] = await Promise.all([
        context.request("/waitlist"), context.request("/follow-ups"),
        context.request("/shift-replacements"), context.loadDoctors(),
    ]);
    body.replaceChildren(
        section("Waitlist", rows(waitlist, (item) => requestCard(
            context.doctorName(item.doctor_id),
            item.offered_start ? `Offered appointment on ${formatDateTime(item.offered_start)}` : formatDay(item.day),
            statusBadge(waitlistStatus(item)), waitlistAction(context, item),
        ), "You have not joined a waitlist.")),
        section("Follow-Ups", rows(followUps, (item) => requestCard(
            context.doctorName(item.doctor_id), `${formatDay(item.start_date)} to ${formatDay(item.end_date)}`,
            item.booked_appointment_id ? statusBadge("booked") : item.end_date < clinicDay() ? statusBadge("expired") : badge("Recommended", "blue"),
            chooseFollowUp(context, item),
        ), "You have no follow-up recommendations.")),
        section("Doctor Replacements", rows(replacements, (item) => requestCard(
            `${context.doctorName(item.original_doctor_id)} to ${context.doctorName(item.replacement_doctor_id)}`,
            formatDateTime(item.starts_at),
            statusBadge(item.status === "pending" && Date.parse(item.starts_at) <= Date.now() ? "stale" : item.status),
            replacementAction(context, item),
        ), "You have no doctor replacement offers.")),
    );
}

export async function renderNotifications(body, context) {
    const notifications = await context.request("/notifications");
    const kinds = {
        waitlist_offer: {title: "Waitlist Offer", path: "/waitlist", action: waitlistAction},
        follow_up: {title: "Follow-Up Recommendation", path: "/follow-ups", action: chooseFollowUp},
        doctor_replacement: {title: "Doctor Replacement", path: "/shift-replacements", action: replacementAction},
    };
    const types = [...new Set(notifications.map((item) => item.kind))].filter((kind) => kinds[kind]);
    const related = new Map(await Promise.all(types.map(async (kind) => [kind, await context.request(kinds[kind].path)])));
    await context.loadDoctors();
    body.replaceChildren(rows(notifications, (item) => {
        const kind = kinds[item.kind];
        const card = requestCard(kind?.title || "Update", item.message, item.read_at ? badge("Read") : badge("Unread", "blue"), null);
        const target = related.get(item.kind)?.find((row) => row.id === item.subject_id);
        const actions = element("div", "", "actions");
        const action = target && kind.action(context, target);
        if (action) actions.append(action);
        if (!item.read_at) actions.append(saveAction("Mark Read", context, `/notifications/${item.id}/read`, "PATCH", null, "Notification marked read."));
        card.append(element("p", formatDateTime(item.created_at), "note"));
        if (actions.childElementCount) card.append(actions);
        return card;
    }, "You have no notifications."));
}
