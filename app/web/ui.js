const dialog = document.querySelector("#action-dialog");
const dialogContent = document.querySelector("#dialog-content");
const dialogError = document.querySelector("#dialog-error");
const status = document.querySelector("#status");

let noticeTimer;

export function element(tag, text = "", className = "") {
    const item = document.createElement(tag);
    item.textContent = text;
    item.className = className;
    return item;
}

export function button(label, onClick, variant = "") {
    const control = element("button", label, `button ${variant}`.trim());
    control.type = "button";
    control.addEventListener("click", () => onClick(control));
    return control;
}

export function badge(label, tone = "") {
    const tag = element("span", label, "badge");
    tag.dataset.tone = tone;
    return tag;
}

export function notice(message, error = false) {
    clearTimeout(noticeTimer);
    status.textContent = message;
    status.classList.toggle("error", error);
    status.hidden = !message;
    if (message) noticeTimer = setTimeout(() => { status.hidden = true; }, 6500);
}

export function openDialog(title, content) {
    document.querySelector("#dialog-title").textContent = title;
    dialogContent.replaceChildren(content);
    dialogError.hidden = true;
    dialogError.textContent = "";
    if (!dialog.open) dialog.showModal();
}

export function closeDialog() {
    if (dialog.open) dialog.close();
}

document.querySelector("#close-dialog").addEventListener("click", closeDialog);
dialog.addEventListener("close", () => {
    if (!dialog.open) dialogContent.replaceChildren();
});

export async function runAction(control, action) {
    const inDialog = dialog.contains(control);
    control.disabled = true;
    if (inDialog) dialogError.hidden = true;
    try {
        await action();
    } catch (error) {
        if (error.name === "AbortError") return;
        if (inDialog && dialog.contains(control) && dialog.open) {
            dialogError.textContent = error.message;
            dialogError.hidden = false;
        } else {
            notice(error.message, true);
        }
    } finally {
        control.disabled = false;
    }
}

export function field(spec) {
    const wrapper = element("label", "", "field");
    wrapper.append(element("span", spec.label));
    const input = element(spec.options ? "select" : spec.type === "textarea" ? "textarea" : "input");
    if (spec.options) updateOptions(input, spec.options);
    else if (input.tagName === "INPUT") input.type = spec.type || "text";
    input.name = spec.name;
    input.required = spec.required !== false;
    if (spec.value != null) input.value = spec.value;
    if (spec.autocomplete) input.autocomplete = spec.autocomplete;
    if (spec.min) input.min = spec.min;
    if (spec.max) input.max = spec.max;
    if (spec.minLength) input.minLength = spec.minLength;
    if (spec.maxLength) input.maxLength = spec.maxLength;
    wrapper.append(input);
    return {wrapper, input};
}

export function updateOptions(select, options) {
    select.replaceChildren();
    for (const option of options) {
        const item = element("option", option.label);
        item.value = option.value;
        select.append(item);
    }
}

export function formDialog(title, fields, submitLabel, submitAction, configure) {
    const form = element("form", "", "form");
    const inputs = {};
    for (const spec of fields) {
        const {wrapper, input} = field(spec);
        form.append(wrapper);
        inputs[spec.name] = input;
    }
    if (configure) configure(inputs);
    const footer = element("div", "", "actions");
    const submit = element("button", submitLabel, "button primary");
    submit.type = "submit";
    footer.append(submit, button("Close", closeDialog));
    form.append(footer);
    form.addEventListener("submit", (event) => {
        event.preventDefault();
        const values = Object.fromEntries(new FormData(form));
        runAction(submit, () => submitAction(values));
    });
    openDialog(title, form);
}

export function detailList(entries) {
    const list = element("dl", "", "details");
    for (const [label, value] of entries) {
        const item = element("div");
        item.append(element("dt", label), element("dd", value || "None"));
        list.append(item);
    }
    return list;
}

export function empty(message) {
    return element("p", message, "empty");
}

export function section(title, content) {
    const group = element("section", "", "section");
    group.append(element("h2", title), content);
    return group;
}

const clinicOffset = 5 * 60 * 60 * 1000;
const dayFormatter = new Intl.DateTimeFormat("en-GB", {dateStyle: "medium", timeZone: "UTC"});
const timeFormatter = new Intl.DateTimeFormat("en-GB", {hour: "2-digit", minute: "2-digit", timeZone: "UTC"});

export function clinicDay(daysAhead = 0) {
    return new Date(Date.now() + clinicOffset + daysAhead * 86400000).toISOString().slice(0, 10);
}

export function formatDay(day) {
    return dayFormatter.format(new Date(`${day}T00:00:00Z`));
}

export function formatTime(timestamp) {
    return timeFormatter.format(new Date(Date.parse(timestamp) + clinicOffset));
}

export function formatDateTime(timestamp) {
    const clinicDate = new Date(Date.parse(timestamp) + clinicOffset);
    return `${dayFormatter.format(clinicDate)} at ${timeFormatter.format(clinicDate)}`;
}
