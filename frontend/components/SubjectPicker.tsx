'use client';

import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react';
import { ChevronDown, BookOpen, RefreshCw } from 'lucide-react';
import { apiClient } from '@/lib/api-client';
import { describeError } from '@/lib/api-errors';
import { useAppStore } from '@/lib/store';
import { isSubjectAvailable } from '@/lib/subjects';
import type { SubjectSummary } from '@/lib/types';
import { useApiQuery } from '@/lib/useApiQuery';

// Colour of subjects whose theme is not loaded (only the current subject's theme is).
const NEUTRAL_SUBJECT_COLOR = '#9ca3af';

type FocusTarget = 'selected' | 'last';

interface SubjectPickerProps {
  className?: string;
}

export default function SubjectPicker({ className = '' }: SubjectPickerProps) {
  const currentSubject = useAppStore((state) => state.currentSubject);
  const setCurrentSubject = useAppStore((state) => state.setCurrentSubject);
  const themeColor = useAppStore((state) =>
    state.subjectTheme?.subject_id === state.currentSubject ? state.subjectTheme.primary_color : null
  );
  const subjectsQuery = useApiQuery('subjects', (signal) => apiClient.getSubjects({ signal }));
  const [isOpen, setIsOpen] = useState(false);

  const listboxId = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const optionRefs = useRef<Array<HTMLLIElement | null>>([]);
  // Index of the option to focus when the list opens
  const focusOnOpenRef = useRef<number | null>(null);

  const subjectList = subjectsQuery.data;
  const subjects = subjectList?.subjects ?? [];
  const currentSubjectInfo = subjects.find((s) => s.id === currentSubject);

  // Switch to the default subject when the remembered one is not offered (anymore), or has no
  // data while the default has.
  useEffect(() => {
    if (!subjectList) return;
    const current = subjectList.subjects.find((s) => s.id === currentSubject);
    const fallback = subjectList.subjects.find((s) => s.id === subjectList.default_subject);
    if (!fallback || fallback.id === currentSubject) return;
    if (!current || (!isSubjectAvailable(current) && isSubjectAvailable(fallback))) {
      setCurrentSubject(fallback.id);
    }
  }, [subjectList, currentSubject, setCurrentSubject]);

  const enabledIndexes = subjects.flatMap((subject, index) =>
    isSubjectAvailable(subject) ? [index] : []
  );

  // Move focus into the list when it opens.
  useEffect(() => {
    if (isOpen && focusOnOpenRef.current !== null) {
      optionRefs.current[focusOnOpenRef.current]?.focus();
    }
  }, [isOpen]);

  const openList = (target: FocusTarget) => {
    const selectedIndex = subjects.findIndex((s) => s.id === currentSubject);
    focusOnOpenRef.current =
      enabledIndexes.length === 0
        ? null
        : target === 'last'
          ? enabledIndexes[enabledIndexes.length - 1]
          : enabledIndexes.includes(selectedIndex)
            ? selectedIndex
            : enabledIndexes[0];
    setIsOpen(true);
  };

  const closeList = (returnFocus: boolean) => {
    setIsOpen(false);
    if (returnFocus) triggerRef.current?.focus();
  };

  const handleSelect = (subject: SubjectSummary) => {
    if (!isSubjectAvailable(subject)) return;
    setCurrentSubject(subject.id);
    closeList(true);
  };

  const handleTriggerKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      openList(event.key === 'ArrowDown' ? 'selected' : 'last');
    }
  };

  const handleListKeyDown = (event: KeyboardEvent<HTMLUListElement>) => {
    const focusedIndex = optionRefs.current.findIndex((el) => el === document.activeElement);
    const position = enabledIndexes.indexOf(focusedIndex);
    const focusEnabled = (enabledPosition: number) => {
      const index = enabledIndexes[Math.max(0, Math.min(enabledIndexes.length - 1, enabledPosition))];
      if (index !== undefined) optionRefs.current[index]?.focus();
    };

    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault();
        focusEnabled(position + 1);
        break;
      case 'ArrowUp':
        event.preventDefault();
        focusEnabled(position === -1 ? enabledIndexes.length - 1 : position - 1);
        break;
      case 'Home':
        event.preventDefault();
        focusEnabled(0);
        break;
      case 'End':
        event.preventDefault();
        focusEnabled(enabledIndexes.length - 1);
        break;
      case 'Enter':
      case ' ':
        event.preventDefault();
        if (focusedIndex >= 0) handleSelect(subjects[focusedIndex]);
        break;
      case 'Escape':
        event.preventDefault();
        closeList(true);
        break;
      case 'Tab':
        closeList(false);
        break;
    }
  };

  if (subjectsQuery.isLoading && !subjectList) {
    return (
      <div className={`flex items-center gap-2 ${className}`}>
        <div className="w-32 h-9 bg-gray-200 animate-pulse rounded-lg" aria-hidden="true"></div>
        <span className="sr-only" role="status">
          Loading subjects
        </span>
      </div>
    );
  }

  if (!subjectList) {
    return (
      <div
        role="alert"
        className={`flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 ${className}`}
      >
        <span>
          Couldn&apos;t load subjects
          <span className="sr-only">: {describeError(subjectsQuery.error)}</span>
        </span>
        <button
          type="button"
          onClick={subjectsQuery.retry}
          className="inline-flex items-center gap-1 font-medium underline hover:text-red-900"
        >
          <RefreshCw className="w-3.5 h-3.5" aria-hidden="true" />
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className={`relative ${className}`}>
      <button
        ref={triggerRef}
        type="button"
        onClick={() => (isOpen ? closeList(false) : openList('selected'))}
        onKeyDown={handleTriggerKeyDown}
        className="flex items-center gap-2 px-3 py-2 bg-white border border-gray-200 rounded-lg shadow-sm hover:bg-gray-50 hover:border-gray-300 transition-all"
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        aria-controls={isOpen ? listboxId : undefined}
      >
        <div
          className="w-3 h-3 rounded-full"
          style={{ backgroundColor: themeColor ?? NEUTRAL_SUBJECT_COLOR }}
          aria-hidden="true"
        />
        <BookOpen className="w-4 h-4 text-gray-500" aria-hidden="true" />
        <span className="text-sm font-medium text-gray-700">
          <span className="sr-only">Subject: </span>
          {currentSubjectInfo?.name || 'Select Subject'}
        </span>
        <ChevronDown
          className={`w-4 h-4 text-gray-400 transition-transform ${isOpen ? 'rotate-180' : ''}`}
          aria-hidden="true"
        />
      </button>

      {isOpen && (
        <>
          {/* Backdrop */}
          <div
            className="fixed inset-0 z-10"
            onClick={() => closeList(false)}
          />

          {/* Dropdown */}
          <ul
            id={listboxId}
            role="listbox"
            aria-label="Subjects"
            onKeyDown={handleListKeyDown}
            className="absolute top-full left-0 mt-1 w-64 bg-white border border-gray-200 rounded-lg shadow-lg z-20 py-1 animate-in fade-in slide-in-from-top-1 duration-150"
          >
            {subjects.map((subject, index) => {
              const available = isSubjectAvailable(subject);
              const selected = subject.id === currentSubject;
              return (
                <li
                  key={subject.id}
                  ref={(element) => {
                    optionRefs.current[index] = element;
                  }}
                  role="option"
                  aria-selected={selected}
                  aria-disabled={available ? undefined : true}
                  tabIndex={-1}
                  onClick={() => handleSelect(subject)}
                  className={`w-full flex items-center gap-3 px-4 py-2.5 transition-colors focus:outline-none focus-visible:bg-gray-100 ${
                    available ? 'cursor-pointer hover:bg-gray-50' : 'cursor-not-allowed opacity-60'
                  } ${selected ? 'bg-gray-50' : ''}`}
                >
                  <div
                    className="w-3 h-3 rounded-full flex-shrink-0"
                    style={{
                      backgroundColor: selected && themeColor ? themeColor : NEUTRAL_SUBJECT_COLOR,
                    }}
                    aria-hidden="true"
                  />
                  <div className="flex-1 text-left">
                    <div className="text-sm font-medium text-gray-900">
                      {subject.name}
                    </div>
                    <div className="text-xs text-gray-500 line-clamp-1">
                      {subject.description}
                    </div>
                  </div>
                  {!available ? (
                    <span className="text-xs text-amber-700 bg-amber-50 px-1.5 py-0.5 rounded whitespace-nowrap">
                      Coming soon
                    </span>
                  ) : subject.is_default ? (
                    <span className="text-xs text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded">
                      Default
                    </span>
                  ) : null}
                  {selected && (
                    <div className="w-2 h-2 rounded-full bg-green-500" aria-hidden="true" />
                  )}
                </li>
              );
            })}
          </ul>
        </>
      )}
    </div>
  );
}
