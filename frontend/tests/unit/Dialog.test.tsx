import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import Dialog from '@/components/Dialog';

function DialogOpener({ withButtons = true }: { withButtons?: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button onClick={() => setOpen(true)}>Open</button>
      {open && (
        <Dialog labelledBy="dialog-title" onClose={() => setOpen(false)}>
          <h2 id="dialog-title">Results</h2>
          {withButtons && (
            <>
              <button onClick={() => setOpen(false)}>First</button>
              <a href="#more">Middle</a>
              <button disabled>Disabled</button>
              <button>Last</button>
            </>
          )}
        </Dialog>
      )}
    </>
  );
}

function openDialog(withButtons?: boolean) {
  render(<DialogOpener withButtons={withButtons} />);
  const opener = screen.getByRole('button', { name: 'Open' });
  opener.focus();
  fireEvent.click(opener);
  return opener;
}

describe('Dialog', () => {
  it('is a labelled modal dialog', () => {
    openDialog();

    const dialog = screen.getByRole('dialog', { name: 'Results' });
    expect(dialog).toHaveAttribute('aria-modal', 'true');
  });

  it('focuses the first focusable element', () => {
    openDialog();

    expect(screen.getByRole('button', { name: 'First' })).toHaveFocus();
  });

  it('keeps Tab and Shift+Tab inside the dialog', () => {
    openDialog();
    const first = screen.getByRole('button', { name: 'First' });
    const last = screen.getByRole('button', { name: 'Last' });

    last.focus();
    fireEvent.keyDown(document, { key: 'Tab' });
    expect(first).toHaveFocus();

    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });
    expect(last).toHaveFocus();

    // Moving between inner elements is left to the browser
    screen.getByRole('link', { name: 'Middle' }).focus();
    fireEvent.keyDown(document, { key: 'Tab' });
    expect(screen.getByRole('link', { name: 'Middle' })).toHaveFocus();
  });

  it('pulls focus back inside when it escaped the dialog', () => {
    const opener = openDialog();

    opener.focus();
    fireEvent.keyDown(document, { key: 'Tab' });

    expect(screen.getByRole('button', { name: 'First' })).toHaveFocus();
  });

  it('focuses the dialog itself when it has nothing focusable', () => {
    openDialog(false);
    const dialog = screen.getByRole('dialog');

    expect(dialog).toHaveFocus();
    fireEvent.keyDown(document, { key: 'Tab' });
    expect(dialog).toHaveFocus();
  });

  it('closes with Escape and returns focus to the opener', () => {
    const opener = openDialog();

    fireEvent.keyDown(document, { key: 'Escape' });

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
  });

  it('ignores other keys', () => {
    openDialog();

    fireEvent.keyDown(document, { key: 'Enter' });

    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('closes on a click outside the panel only', () => {
    openDialog();

    fireEvent.click(screen.getByRole('heading', { name: 'Results' }));
    expect(screen.getByRole('dialog')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('dialog').parentElement as HTMLElement);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});
