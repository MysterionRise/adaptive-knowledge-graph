// Thin wrappers over browser APIs that jsdom won't let tests redefine (e.g. window.location).

export function reloadPage(): void {
  window.location.reload();
}
