import {
    badge, button, clinicDay, element, empty, formDialog, formatDateTime, runAction, section, updateOptions,
} from "./ui.js";

function saveButton(label, context, path, method, message) {
    return button(label, (control) => runAction(control, () => context.save(path, {method}, message)), "primary");
}

function chooseReplacement(context, doctors) {
    const options = doctors.map((doctor) => ({value: doctor.id, label: `${doctor.name} (${doctor.specialty_name})`}));
    formDialog("Replace a Doctor's Shift", [
        {name: "doctor_id", label: "Doctor", options},
        {name: "replacement_doctor_id", label: "Replacement Doctor", options: []},
        {name: "date", label: "Date of the Shift", type: "date", value: clinicDay(1), min: clinicDay()},
    ], "Offer Replacement", (values) => context.save("/shift-replacements", {
        method: "POST",
        body: {...values, doctor_id: Number(values.doctor_id), replacement_doctor_id: Number(values.replacement_doctor_id)},
    }, "The shift is closed. Replacement offers were sent to the affected patients."), (inputs) => {
        function chooseSpecialty() {
            const current = doctors.find((doctor) => doctor.id === Number(inputs.doctor_id.value));
            const matching = doctors.filter((doctor) => doctor.specialty_id === current?.specialty_id && doctor.id !== current?.id);
            const replacements = matching.map((doctor) => ({value: doctor.id, label: doctor.name}));
            updateOptions(inputs.replacement_doctor_id, replacements.length ? replacements : [{value: "", label: "No other doctor in this specialty"}]);
        }
        inputs.doctor_id.addEventListener("change", chooseSpecialty);
        chooseSpecialty();
    });
}

async function addDoctor(context) {
    const specialties = await context.request("/specialties");
    if (!specialties.length) throw new Error("Create a specialty before adding a doctor.");
    formDialog("Create Doctor", [
        {name: "name", label: "Full Name", minLength: 2, maxLength: 120, autocomplete: "off"},
        {name: "email", label: "Email", type: "email", autocomplete: "off"},
        {name: "password", label: "Temporary Password", type: "password", minLength: 8, maxLength: 128, autocomplete: "new-password"},
        {name: "specialty_id", label: "Specialty", options: specialties.map((item) => ({value: item.id, label: item.name}))},
    ], "Create Doctor", (values) => context.save("/doctors", {
        method: "POST", body: {...values, specialty_id: Number(values.specialty_id)},
    }, "Doctor created. They can now sign in and set their working hours."));
}

export async function renderReplacements(body, context) {
    const [doctors, replacements] = await Promise.all([context.loadDoctors(), context.request("/shift-replacements")]);
    const actions = element("div", "", "actions");
    const create = button("Replace a Shift", () => chooseReplacement(context, doctors), "primary");
    create.disabled = docsWithoutSameSpecialty(doctors);
    actions.append(create, button("Create Doctor", (control) => runAction(control, () => addDoctor(context))));
    const items = element("div", "", "stack");
    const labels = {pending: "Awaiting Confirmation", accepted: "Confirmed", stale: "Unavailable"};
    for (const item of replacements) {
        const card = element("article", "", "card");
        const header = element("div", "", "card-top");
        const state = item.status === "pending" && Date.parse(item.starts_at) <= Date.now() ? "stale" : item.status;
        header.append(element("h3", `${context.doctorName(item.original_doctor_id)} to ${context.doctorName(item.replacement_doctor_id)}`),
            badge(labels[state] || "Unknown", state === "accepted" ? "green" : state === "pending" ? "amber" : ""));
        card.append(header, element("p", formatDateTime(item.starts_at), "muted"));
        items.append(card);
    }
    body.replaceChildren(actions);
    if (create.disabled) body.append(element("p", "Add another active doctor in the same specialty and set their working hours to replace a shift.", "note"));
    body.append(section("Replacement Offers", replacements.length ? items : empty("No replacement offers have been made.")));
}

function docsWithoutSameSpecialty(doctors) {
    return new Set(doctors.map((doctor) => doctor.specialty_id)).size === doctors.length;
}

export async function renderReviews(body, context) {
    const [reviews] = await Promise.all([context.request("/admin/reviews"), context.loadDoctors()]);
    const pending = reviews.filter((review) => review.status === "pending");
    const list = element("div", "", "stack");
    for (const review of pending) {
        const card = element("article", "", "card");
        const header = element("div", "", "card-top");
        header.append(element("h3", context.doctorName(review.doctor_id)), badge(`${review.rating} / 5`, "amber"));
        const actions = element("div", "", "actions");
        actions.append(saveButton("Publish Review", context, `/admin/reviews/${review.id}/publish`, "PATCH", "Review published. The doctor's rating has been updated."));
        card.append(header, element("p", review.comment || "Rating only", "multiline"), actions);
        list.append(card);
    }
    body.replaceChildren(pending.length ? list : empty("No reviews are awaiting moderation."));
}

export async function renderCertificates(body, context) {
    const certificates = await context.request("/admin/certificates");
    const pending = certificates.filter((item) => item.status === "pending");
    const list = element("div", "", "stack");
    for (const item of pending) {
        const card = element("article", "", "card");
        const header = element("div", "", "card-top");
        header.append(element("h3", item.patient_name), badge("Awaiting Approval", "amber"));
        const actions = element("div", "", "actions");
        actions.append(saveButton("Approve Certificate", context, `/admin/certificates/${item.appointment_id}/approve`, "PATCH", "Certificate approved. The patient can now download it."));
        card.append(header, element("p", item.doctor_name), element("p", formatDateTime(item.starts_at), "muted"), actions);
        list.append(card);
    }
    body.replaceChildren(pending.length ? list : empty("No certificates are awaiting approval."));
}
