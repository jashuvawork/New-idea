/** IST session windows for the live strategy playbook UI. */

export function istMinutesNow(date = new Date()): number {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Kolkata',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).formatToParts(date);
  const hour = Number(parts.find((p) => p.type === 'hour')?.value ?? 0);
  const minute = Number(parts.find((p) => p.type === 'minute')?.value ?? 0);
  return hour * 60 + minute;
}

export function inIstWindow(startH: number, startM: number, endH: number, endM: number, now = new Date()): boolean {
  const t = istMinutesNow(now);
  const start = startH * 60 + startM;
  const end = endH * 60 + endM;
  return t >= start && t < end;
}

export function morningCaptureWindowActive(now = new Date()): boolean {
  return inIstWindow(9, 15, 11, 45, now);
}

export function momentumRallyWindowActive(now = new Date()): boolean {
  return inIstWindow(10, 0, 15, 25, now);
}

export function allDayExplosionWindowActive(now = new Date()): boolean {
  return inIstWindow(9, 20, 15, 25, now);
}

export function openCautionWindowActive(now = new Date()): boolean {
  return inIstWindow(9, 15, 9, 45, now);
}

export function primaryWindowActive(now = new Date()): boolean {
  return istMinutesNow(now) >= 10 * 60;
}

export function formatIstTime(date = new Date()): string {
  return new Intl.DateTimeFormat('en-IN', {
    timeZone: 'Asia/Kolkata',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date);
}
