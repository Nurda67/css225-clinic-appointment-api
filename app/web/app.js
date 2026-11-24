import {
    badge, button, clinicDay, closeDialog, detailList, element, empty, field,
    formDialog, formatDateTime, formatTime, notice, openDialog, runAction,
} from "./ui.js";
import {renderAppointments, renderNotifications, renderRequests} from "./appointments.js";
import {renderCertificates, renderReplacements, renderReviews} from "./administration.js";

const navigation = document.querySelector("#navigation");
const screen = document.querySelector("#screen");
const accountActions = document.querySelector("#account-actions");

const pages = {
    directory: {label: "Find a Doctor", render: renderDirectory},
    appointments: {label: "Appointments", render: renderAppointments},
    requests: {label: "Requests", render: renderRequests},
    notifications: {label: "Notifications", render: renderNotifications},
    replacements: {label: "Shift Replacements", render: renderReplacements},
    reviews: {label: "Review Moderation", render: renderReviews},
    certificates: {label: "Certificates", render: renderCertificates},
};
const rolePages = {
    patient: ["appointments", "requests", "notifications"],
    doctor: ["appointments", "notifications"],
    admin: ["replacements", "reviews", "certificates", "notifications"],
};
const roleLabels = {patient: "Patient", doctor: "Doctor", admin: "Administrator"};
const doctorsById = new Map();
let user = null;
let token = null;
let activePage = "directory";
let unreadCount = 0;
let renderVersion = 0;
let sessionVersion = 0;
let noticeRefresh = null;

async function request(path, {method = "GET", body, download = false} = {}) {
    const requestVersion = sessionVersion;
    const headers = new Headers();
    if (token) headers.set("Authorization", `Bearer ${token}`);
    if (body != null) headers.set("Content-Type", "application/json");
    let response;
    try {
        response = await fetch(path, {
            method, headers, cache: "no-store",
            body: body == null ? undefined : JSON.stringify(body),
        });
    } catch {
        throw new Error("The clinic service could not be reached. Try again.");
    }
    let data = null;
    if (response.status !== 204) {
        data = response.ok && download ? await response.blob() : await response.json().catch(() => null);
    }
    if (requestVersion !== sessionVersion) {
        throw new DOMException("The account changed before the request finished.", "AbortError");
    }
    if (!response.ok) {
        const error = new Error(data?.error?.message || data?.detail || "The request could not be completed.");
        error.status = response.status;
        throw error;
    }
    return data;
}

async function loadDoctors() {
    const doctors = await request("/doctors");
    for (const doctor of doctors) doctorsById.set(doctor.id, doctor);
    return doctors;
}

function doctorName(id) {
    return doctorsById.get(id)?.name || `Doctor ${id}`;
}

function paintNavigation() {
    const keys = ["directory", ...(rolePages[user?.role] || [])];
    const currentFocus = document.activeElement?.dataset.page;
    navigation.replaceChildren();
    for (const key of keys) {
        const item = button(pages[key].label, () => showPage(key));
        item.className = "nav-button";
        item.dataset.page = key;
        if (key === activePage) item.setAttribute("aria-current", "page");
        if (key === "notifications" && unreadCount) {
            const count = element("span", String(unreadCount), "nav-count");
            count.setAttribute("aria-label", `${unreadCount} unread`);
            item.append(count);
        }
        navigation.append(item);
        if (key === currentFocus) item.focus();
    }
}

function paintAccount() {
    accountActions.replaceChildren();
    if (user) {
        accountActions.append(
            element("span", user.name, "account-name"),
            element("span", roleLabels[user.role] || "Member", "account-role"),
            button("Sign Out", signOut),
        );
    } else {
        accountActions.append(button("Register", () => authenticate(true)), button("Sign In", () => authenticate(false), "primary"));
    }
}

async function showPage(key, moveFocus = true) {
    activePage = key;
    const version = ++renderVersion;
    paintNavigation();
    const title = element("h1", pages[key].label);
    title.id = "page-title";
    const header = element("header", "", "page-header");
    header.append(title);
    if (key !== "directory") header.append(button("Refresh", () => showPage(key, false)));
    const body = element("div", "", "screen-body");
    body.setAttribute("aria-busy", "true");
    body.append(empty("Loading…"));
    screen.replaceChildren(header, body);
    if (moveFocus) screen.focus();
    try {
        await pages[key].render(body, context);
    } catch (error) {
        if (version === renderVersion) {
            body.replaceChildren(element("p", error.message, "feedback error"), button("Try Again", () => showPage(key, false)));
        }
    } finally {
        body.removeAttribute("aria-busy");
    }
}

async function refreshUnread() {
    if (!user) return;
    const session = token;
    try {
        const list = await request("/notifications");
        if (session !== token) return;
        const count = list.filter((item) => !item.read_at).length;
        if (unreadCount !== count) {
            unreadCount = count;
            paintNavigation();
        }
    } catch {
        // The Notifications page reports fetch errors when opened explicitly.
    }
}

async function save(path, options, success) {
    await request(path, options);
    closeDialog();
    notice(success);
    await Promise.all([showPage(activePage, false), refreshUnread()]);
}

function signOut() {
    sessionVersion += 1;
    clearInterval(noticeRefresh);
    token = null;
    user = null;
    unreadCount = 0;
    closeDialog();
    paintAccount();
    notice("Signed out.");
    showPage("directory");
}

function authenticate(register) {
    const fields = [
        {name: "email", label: "Email", type: "email", autocomplete: "username"},
        {name: "password", label: "Password", type: "password", autocomplete: register ? "new-password" : "current-password", minLength: register ? 8 : undefined, maxLength: 128},
    ];
    if (register) fields.unshift({name: "name", label: "Full Name", autocomplete: "name", minLength: 2, maxLength: 120});
    const title = register ? "Create Patient Account" : "Sign In";
    formDialog(title, fields, register ? "Create Account" : "Sign In", async (values) => {
        const credentials = {email: values.email, password: values.password};
        if (register) await request("/auth/register", {method: "POST", body: values});
        const response = await request("/auth/login", {method: "POST", body: credentials});
        const signInVersion = ++sessionVersion;
        token = response.access_token;
        try {
            user = await request("/auth/me");
        } catch (error) {
            if (signInVersion === sessionVersion) token = null;
            throw error;
        }
        closeDialog();
        paintAccount();
        notice(register ? "Your patient account is ready." : "Signed in.");
        clearInterval(noticeRefresh);
        noticeRefresh = setInterval(refreshUnread, 12000);
        await Promise.all([showPage(rolePages[user.role]?.[0] || "directory"), refreshUnread()]);
    });
}

function chooseSlot({doctorId, title, actionLabel, path, method = "POST", firstDay, lastDay, allowWaitlist = false, success}) {
    const content = element("div", "", "slot-dialog");
    const today = clinicDay();
    const earliest = firstDay && firstDay > today ? firstDay : today;
    const date = field({label: "Date", name: "date", type: "date", min: earliest, max: lastDay, value: earliest});
    const times = element("div", "", "slots");
    times.setAttribute("aria-label", "Available times");
    times.setAttribute("aria-live", "polite");
    const actions = element("div", "", "actions");
    let startsAt = null;
    let lookup = 0;
    let submit;
    let join;

    if (path) {
        submit = button(actionLabel, (control) => runAction(control, async () => {
            const body = path === "/appointments" ? {doctor_id: doctorId, starts_at: startsAt} : {starts_at: startsAt};
            await save(path, {method, body}, success);
        }), "primary");
        submit.disabled = true;
        actions.append(submit);
    } else if (!user) {
        actions.append(button("Sign In to Book", () => authenticate(false), "primary"));
    }
    if (allowWaitlist) {
        join = button("Join Waitlist", (control) => runAction(control, () => save(
            "/waitlist", {method: "POST", body: {doctor_id: doctorId, date: date.input.value}},
            "Added to the waitlist. Check Notifications for a slot offer.",
        )));
        actions.append(join);
    }
    content.append(element("p", doctorName(doctorId), "muted"), date.wrapper,
        element("p", "Clinic time (UTC+05:00)", "note"), times, actions);
    openDialog(title, content);

    async function loadTimes() {
        const attempt = ++lookup;
        startsAt = null;
        if (submit) submit.disabled = true;
        if (join) join.disabled = true;
        if (!date.input.value || !date.input.validity.valid) {
            times.replaceChildren(empty("Choose a date in the available range."));
            return;
        }
        times.replaceChildren(element("p", "Loading times…", "muted"));
        try {
            const slots = await request(`/doctors/${doctorId}/slots?date=${encodeURIComponent(date.input.value)}`);
            if (attempt !== lookup || !content.isConnected) return;
            if (join) join.disabled = false;
            if (!slots.length) {
                times.replaceChildren(empty("No open slots on this date."));
                return;
            }
            times.replaceChildren();
            for (const slot of slots) {
                const label = `${formatTime(slot.starts_at)} to ${formatTime(slot.ends_at)}`;
                if (!submit) {
                    times.append(badge(label));
                    continue;
                }
                const choice = button(label, () => {
                    for (const sibling of times.querySelectorAll("button")) sibling.setAttribute("aria-pressed", "false");
                    choice.setAttribute("aria-pressed", "true");
                    startsAt = slot.starts_at;
                    submit.disabled = false;
                }, "slot");
                choice.setAttribute("aria-pressed", "false");
                times.append(choice);
            }
        } catch (error) {
            if (attempt === lookup) times.replaceChildren(element("p", error.message, "feedback error"));
        }
    }
    date.input.addEventListener("change", loadTimes);
    loadTimes();
}

function initials(name) {
    return name.trim().split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase();
}

function ratingLabel(summary) {
    if (!summary || !summary.review_count) return "No reviews yet";
    const count = summary.review_count;
    return `${Number(summary.average_rating).toFixed(1)} / 5 (${count} ${count === 1 ? "review" : "reviews"})`;
}

function showDoctorReviews(doctor, summary) {
    const content = element("div", "", "stack");
    content.append(element("p", ratingLabel(summary), "rating"));
    for (const review of summary?.reviews || []) {
        const card = element("article", "", "card");
        card.append(element("strong", `${review.rating} / 5`));
        if (review.comment) card.append(element("p", review.comment, "multiline"));
        content.append(card);
    }
    openDialog(`Reviews for ${doctor.name}`, content);
}

async function renderDirectory(body) {
    const doctors = await loadDoctors();
    const reviews = await Promise.allSettled(doctors.map((doctor) => request(`/doctors/${doctor.id}/reviews`)));
    const search = field({name: "doctor-search", label: "Search by Name or Specialty", type: "search", required: false});
    search.wrapper.classList.add("search-field");
    const grid = element("div", "", "grid");

    function paintCards() {
        const query = search.input.value.trim().toLowerCase();
        grid.replaceChildren();
        doctors.forEach((doctor, index) => {
            if (!`${doctor.name} ${doctor.specialty_name}`.toLowerCase().includes(query)) return;
            const summary = reviews[index].status === "fulfilled" ? reviews[index].value : null;
            const card = element("article", "", "card doctor-card");
            const profile = element("div", "", "doctor-info");
            const avatar = element("span", initials(doctor.name), "avatar");
            avatar.setAttribute("aria-hidden", "true");
            const identity = element("div");
            identity.append(element("h3", doctor.name), element("p", doctor.specialty_name, "muted"));
            profile.append(avatar, identity);
            const actions = element("div", "", "actions");
            actions.append(button("View Availability", () => chooseSlot({
                doctorId: doctor.id, title: "Availability", actionLabel: "Book Appointment",
                path: user?.role === "patient" ? "/appointments" : null,
                allowWaitlist: user?.role === "patient", success: "Appointment booked.",
            }), "primary"));
            if (summary?.review_count) actions.append(button("Read Reviews", () => showDoctorReviews(doctor, summary)));
            card.append(profile, element("p", ratingLabel(summary), "rating"), actions);
            grid.append(card);
        });
        if (!grid.childElementCount) grid.append(empty(query ? "No doctors match your search." : "No doctors are available."));
    }

    search.input.addEventListener("input", paintCards);
    body.replaceChildren(search.wrapper, grid);
    paintCards();
}

async function showConsultation(appointmentId) {
    const record = await request(`/appointments/${appointmentId}/medical-record`);
    openDialog("Consultation", detailList([
        ["Completed", formatDateTime(record.created_at)], ["Result", record.diagnosis], ["Notes", record.notes],
    ]));
}

async function downloadCertificate(appointmentId) {
    const blob = await request(`/appointments/${appointmentId}/certificate.pdf`, {download: true});
    const url = URL.createObjectURL(blob);
    const link = element("a");
    link.href = url;
    link.download = `attendance-${appointmentId}.pdf`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1500);
}

const context = {
    get user() { return user; },
    request, save, loadDoctors, doctorName, chooseSlot, showConsultation, downloadCertificate,
};

paintAccount();
showPage("directory", false);
