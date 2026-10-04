'use client';

import { useEffect, useId, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
    Loader2,
    CheckCircle,
    XCircle,
    Circle,
    CircleDot,
    BookOpen,
    Trophy,
    RotateCcw,
    MapPin,
    Zap,
    RefreshCw,
    AlertCircle,
    AlertTriangle,
    X,
} from 'lucide-react';
import { apiClient } from '@/lib/api-client';
import { describeError, isAbortError } from '@/lib/api-errors';
import { INITIAL_MASTERY, targetDifficultyFor } from '@/lib/mastery';
import { useAppStore } from '@/lib/store';
import type {
    AdaptiveQuiz,
    Difficulty,
    Quiz as QuizData,
    QuizQuestionResult,
    RecommendationResponse,
} from '@/lib/types';
import Dialog from './Dialog';
import MasteryIndicator from './MasteryIndicator';
import PostQuizRecommendations from './PostQuizRecommendations';
import LearningPath from './LearningPath';

const QUESTIONS_PER_QUIZ = 3;
const RESET_NOTICE_MS = 3000;
const CUSTOM_TOPIC = '__custom__';
// Longest topic all quiz endpoints accept (mastery updates allow at most 200 characters).
const MAX_TOPIC_LENGTH = 200;

interface TopicOption {
    value: string;
    label: string;
}

type RecommendationsState =
    | { status: 'idle' }
    | { status: 'loading' }
    | { status: 'success'; data: RecommendationResponse }
    | { status: 'error'; message: string };

type ResetStatus = { type: 'success' } | { type: 'error'; message: string } | null;

const DifficultyBadge = ({ difficulty }: { difficulty?: Difficulty | null }) => {
    if (!difficulty) return null;

    const badges = {
        easy: {
            bg: 'bg-green-100',
            text: 'text-green-700',
            border: 'border-green-200',
            label: 'Easy'
        },
        medium: {
            bg: 'bg-yellow-100',
            text: 'text-yellow-700',
            border: 'border-yellow-200',
            label: 'Medium'
        },
        hard: {
            bg: 'bg-red-100',
            text: 'text-red-700',
            border: 'border-red-200',
            label: 'Hard'
        }
    };

    const badge = badges[difficulty];

    return (
        <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border ${badge.bg} ${badge.text} ${badge.border}`}>
            {badge.label}
        </span>
    );
};

// Subject-specific topic lists — curated to match OpenStax textbook content
const SUBJECT_TOPICS: Record<string, TopicOption[]> = {
    us_history: [
        { value: 'The American Revolution', label: 'The American Revolution' },
        { value: 'The Constitution', label: 'The Constitution' },
        { value: 'Colonial America', label: 'Colonial America' },
        { value: 'The Civil War', label: 'The Civil War' },
        { value: 'Industrialization', label: 'Industrialization' },
        { value: 'Westward Expansion', label: 'Westward Expansion' },
        { value: 'World War II', label: 'World War II' },
        { value: 'The Great Depression', label: 'The Great Depression' },
        { value: 'Civil Rights Movement', label: 'Civil Rights Movement' },
        { value: 'Cold War', label: 'Cold War' },
        { value: 'Slavery and Abolition', label: 'Slavery and Abolition' },
        { value: 'Immigration and Urbanization', label: 'Immigration and Urbanization' },
    ],
    economics: [
        { value: 'Supply and Demand', label: 'Supply and Demand' },
        { value: 'Market Equilibrium', label: 'Market Equilibrium' },
        { value: 'Fiscal Policy', label: 'Fiscal Policy' },
        { value: 'Monetary Policy', label: 'Monetary Policy' },
        { value: 'International Trade', label: 'International Trade' },
        { value: 'Monopoly and Competition', label: 'Monopoly and Competition' },
        { value: 'Inflation and Unemployment', label: 'Inflation and Unemployment' },
        { value: 'GDP and Economic Growth', label: 'GDP and Economic Growth' },
        { value: 'Labor Markets', label: 'Labor Markets' },
        { value: 'Poverty and Inequality', label: 'Poverty and Inequality' },
    ],
    biology: [
        { value: 'Cell Structure and Function', label: 'Cell Structure and Function' },
        { value: 'Photosynthesis', label: 'Photosynthesis' },
        { value: 'DNA and Genetics', label: 'DNA and Genetics' },
        { value: 'Evolution and Natural Selection', label: 'Evolution and Natural Selection' },
        { value: 'Ecology and Ecosystems', label: 'Ecology and Ecosystems' },
    ],
    world_history: [
        { value: 'Ancient Civilizations', label: 'Ancient Civilizations' },
        { value: 'The Roman Empire', label: 'The Roman Empire' },
        { value: 'The Renaissance', label: 'The Renaissance' },
        { value: 'World War I', label: 'World War I' },
        { value: 'Colonialism and Imperialism', label: 'Colonialism and Imperialism' },
    ],
};

const DEFAULT_TOPICS = SUBJECT_TOPICS.us_history;

/**
 * Dropdown value and custom-topic text for a topic name: the listed topic when it is one of
 * the subject's topics (case-insensitive), otherwise a custom topic.
 */
function topicSelection(name: string | undefined, topics: TopicOption[]) {
    const wanted = name?.trim();
    if (!wanted) return { topic: topics[0].value, customTopic: '' };
    const listed = topics.find((t) => t.value.toLowerCase() === wanted.toLowerCase());
    return listed
        ? { topic: listed.value, customTopic: '' }
        : { topic: CUSTOM_TOPIC, customTopic: wanted.slice(0, MAX_TOPIC_LENGTH) };
}

const withoutFinalPeriod = (text: string) => text.replace(/\.+$/, '');

// Check if quiz is adaptive
const isAdaptiveQuiz = (q: QuizData | AdaptiveQuiz | null): q is AdaptiveQuiz => {
    return q !== null && 'adapted' in q && q.adapted === true;
};

function SyncNotice({ message }: { message: string | null }) {
    if (!message) return null;
    return (
        <div role="status" className="mb-3 p-3 bg-amber-50 border border-amber-200 rounded-md flex items-start gap-2">
            <AlertTriangle className="w-4 h-4 text-amber-500 flex-shrink-0 mt-0.5" aria-hidden="true" />
            <p className="text-sm text-amber-800">
                Your progress could not be synced with the server: {message}
            </p>
        </div>
    );
}

interface QuizProps {
    /** Topic to preselect, e.g. from `/assessment?topic=...`. */
    initialTopic?: string;
}

/**
 * Adaptive assessment. Changing the subject (or the requested topic) starts a new session, so
 * no quiz, result or topic from the previous subject is shown.
 */
export default function Quiz({ initialTopic }: QuizProps) {
    const currentSubject = useAppStore((state) => state.currentSubject);
    return (
        <QuizSession
            key={`${currentSubject}\n${initialTopic ?? ''}`}
            subject={currentSubject}
            initialTopic={initialTopic}
        />
    );
}

function QuizSession({ subject, initialTopic }: { subject: string; initialTopic?: string }) {
    const router = useRouter();
    // Get topics for the current subject
    const subjectTopics = SUBJECT_TOPICS[subject] || DEFAULT_TOPICS;

    const [topic, setTopic] = useState(() => topicSelection(initialTopic, subjectTopics).topic);
    const [customTopic, setCustomTopic] = useState(
        () => topicSelection(initialTopic, subjectTopics).customTopic
    );
    const [quiz, setQuiz] = useState<AdaptiveQuiz | QuizData | null>(null);
    const [currentQuestionIndex, setCurrentQuestionIndex] = useState(0);
    const [selectedOption, setSelectedOption] = useState<string | null>(null);
    const [isSubmitted, setIsSubmitted] = useState(false);
    const [isLoading, setIsLoading] = useState(false);
    const [score, setScore] = useState(0);
    const [showResults, setShowResults] = useState(false);

    // The topic being quizzed (resolved from dropdown or custom input when the quiz starts)
    const [activeTopic, setActiveTopic] = useState('');

    // Adaptive mode state
    const [adaptiveMode, setAdaptiveMode] = useState(true);

    // Post-quiz recommendations state
    const [questionResults, setQuestionResults] = useState<QuizQuestionResult[]>([]);
    const [recommendations, setRecommendations] = useState<RecommendationsState>({ status: 'idle' });

    // Inline error/notice state
    const [formError, setFormError] = useState<string | null>(null);
    const [resetStatus, setResetStatus] = useState<ResetStatus>(null);
    const [isResetting, setIsResetting] = useState(false);

    const masteryMap = useAppStore((state) => state.masteryMap);
    const lastSyncError = useAppStore((state) => state.lastSyncError);
    const updateMastery = useAppStore((state) => state.updateMastery);
    const setHighlightedConcepts = useAppStore((state) => state.setHighlightedConcepts);
    const loadMasteryFromBackend = useAppStore((state) => state.loadMasteryFromBackend);
    const resetMasteryOnBackend = useAppStore((state) => state.resetMasteryOnBackend);

    const baseId = useId();
    const ids = {
        adaptiveLabel: `${baseId}-adaptive-label`,
        adaptiveHint: `${baseId}-adaptive-hint`,
        topic: `${baseId}-topic`,
        customTopic: `${baseId}-custom-topic`,
        results: `${baseId}-results`,
    };
    const startHeadingRef = useRef<HTMLHeadingElement>(null);
    const questionHeadingRef = useRef<HTMLHeadingElement>(null);
    const feedbackHeadingRef = useRef<HTMLHeadingElement>(null);
    const focusStartHeadingRef = useRef(false);
    // Quiz generation or recommendations request in flight
    const requestRef = useRef<AbortController | null>(null);

    const selectedTopic = topic === CUSTOM_TOPIC ? customTopic.trim() : topic;
    // The start form shows the mastery of the selected topic, a running quiz that of its topic.
    const masteryTopic = quiz || isLoading ? activeTopic : selectedTopic;
    const storedMastery = masteryTopic ? masteryMap[masteryTopic]?.masteryLevel : undefined;
    const currentMastery =
        storedMastery ?? (isAdaptiveQuiz(quiz) ? quiz.student_mastery : INITIAL_MASTERY);
    const targetDifficulty = targetDifficultyFor(currentMastery);

    // Load mastery from backend on mount
    useEffect(() => {
        void loadMasteryFromBackend();
    }, [loadMasteryFromBackend]);

    // Cancel a request that is still running when the session ends
    useEffect(() => () => requestRef.current?.abort(), []);

    // The success notice dismisses itself
    useEffect(() => {
        if (resetStatus?.type !== 'success') return;
        const timer = setTimeout(() => setResetStatus(null), RESET_NOTICE_MS);
        return () => clearTimeout(timer);
    }, [resetStatus]);

    // Keep keyboard and screen-reader focus on the part of the quiz that just changed
    useEffect(() => {
        if (quiz) {
            questionHeadingRef.current?.focus();
        } else if (focusStartHeadingRef.current) {
            focusStartHeadingRef.current = false;
            startHeadingRef.current?.focus();
        }
    }, [quiz, currentQuestionIndex]);

    useEffect(() => {
        if (isSubmitted) feedbackHeadingRef.current?.focus();
    }, [isSubmitted]);

    const startRequest = () => {
        requestRef.current?.abort();
        const controller = new AbortController();
        requestRef.current = controller;
        return controller;
    };

    const handleStartQuiz = async () => {
        const effectiveTopic = selectedTopic;
        if (!effectiveTopic) {
            setFormError('Please enter a topic.');
            return;
        }
        setFormError(null);
        setResetStatus(null);
        setActiveTopic(effectiveTopic);
        setIsLoading(true);
        const { signal } = startRequest();
        try {
            const data = adaptiveMode
                ? await apiClient.generateAdaptiveQuiz(effectiveTopic, QUESTIONS_PER_QUIZ, subject, { signal })
                : await apiClient.generateQuiz(effectiveTopic, QUESTIONS_PER_QUIZ, subject, { signal });

            if (!data.questions || data.questions.length === 0) {
                setFormError('The generated quiz has no questions. Try a different topic.');
                return;
            }

            setQuiz(data);
            setCurrentQuestionIndex(0);
            setScore(0);
            setIsSubmitted(false);
            setSelectedOption(null);
            setQuestionResults([]);
        } catch (error) {
            if (isAbortError(error)) return;
            setFormError(`Failed to generate quiz: ${withoutFinalPeriod(describeError(error))}.`);
        } finally {
            setIsLoading(false);
        }
    };

    const handleOptionSelect = (optionId: string) => {
        if (!isSubmitted) {
            setSelectedOption(optionId);
        }
    };

    const handleSubmitAnswer = () => {
        if (!selectedOption || isSubmitted) return;
        setIsSubmitted(true);

        const currentQ = quiz?.questions[currentQuestionIndex];
        const isCorrect = selectedOption === currentQ?.correct_option_id;

        if (isCorrect) {
            setScore(s => s + 1);
        }

        // Track question result for recommendations
        setQuestionResults(prev => [
            ...prev,
            {
                question_id: currentQ?.id || '',
                related_concept: currentQ?.related_concept || activeTopic,
                correct: isCorrect,
            },
        ]);

        // Update mastery tracking for the topic (syncs to backend via BKT)
        updateMastery(activeTopic, isCorrect);
    };

    const fetchRecommendations = async () => {
        setRecommendations({ status: 'loading' });
        const { signal } = startRequest();
        try {
            const data = await apiClient.getQuizRecommendations(
                {
                    topic: activeTopic,
                    question_results: questionResults,
                    student_id: 'default',
                    subject,
                },
                { signal }
            );
            setRecommendations({ status: 'success', data });
        } catch (error) {
            if (isAbortError(error)) return;
            setRecommendations({
                status: 'error',
                message: `Unable to load recommendations: ${withoutFinalPeriod(describeError(error))}. Your score and results are still available above.`,
            });
        }
    };

    const handleNextQuestion = () => {
        if (!quiz) return;
        if (currentQuestionIndex < quiz.questions?.length - 1) {
            setCurrentQuestionIndex(prev => prev + 1);
            setSelectedOption(null);
            setIsSubmitted(false);
        } else {
            // Quiz finished - show results modal
            setShowResults(true);
            // Fetch recommendations asynchronously
            void fetchRecommendations();
        }
    };

    // Close the results and go back to the start form
    const handleCloseResults = () => {
        requestRef.current?.abort();
        focusStartHeadingRef.current = true;
        setQuiz(null);
        setShowResults(false);
        setCurrentQuestionIndex(0);
        setScore(0);
        setSelectedOption(null);
        setIsSubmitted(false);
        setQuestionResults([]);
        setRecommendations({ status: 'idle' });
        setFormError(null);
    };

    const handleResetProfile = async () => {
        setResetStatus(null);
        setIsResetting(true);
        try {
            await resetMasteryOnBackend();
            setResetStatus({ type: 'success' });
        } catch (error) {
            setResetStatus({ type: 'error', message: describeError(error) });
        } finally {
            setIsResetting(false);
        }
    };

    const handleViewLearningPath = () => {
        // Set highlighted concepts before navigating to graph
        setHighlightedConcepts([activeTopic]);
        router.push('/graph');
    };

    // "Practice This" selects the concept: a listed topic, or a custom topic otherwise
    const handlePracticeConcept = (concept: string) => {
        handleCloseResults();
        const selection = topicSelection(concept, subjectTopics);
        setTopic(selection.topic);
        setCustomTopic(selection.customTopic);
    };

    const handleAskTutor = (concept: string) => {
        router.push(`/chat?question=${encodeURIComponent(`Explain ${concept}`)}`);
    };

    if (isLoading) {
        return (
            <div className="flex flex-col items-center justify-center p-12" role="status">
                {/* Animated quiz generation indicator */}
                <div className="relative mb-6" aria-hidden="true">
                    <Loader2 className="w-16 h-16 animate-spin text-blue-600" />
                    <div className="absolute inset-0 flex items-center justify-center">
                        <BookOpen className="w-6 h-6 text-blue-500" />
                    </div>
                </div>

                <h3 className="text-lg font-semibold text-gray-800 mb-2">
                    {adaptiveMode ? 'Crafting Your Personalized Quiz' : 'Generating Quiz'}
                </h3>

                {/* Progress steps */}
                <div className="space-y-2 text-sm text-gray-500 mb-4">
                    <div className="flex items-center gap-2">
                        <span className="w-5 h-5 rounded-full bg-green-100 text-green-600 flex items-center justify-center text-xs" aria-hidden="true">
                            <CheckCircle className="w-3 h-3" />
                        </span>
                        <span>Retrieving context from knowledge graph</span>
                    </div>
                    <div className="flex items-center gap-2">
                        <span className="w-5 h-5 rounded-full bg-blue-100 text-blue-600 flex items-center justify-center" aria-hidden="true">
                            <Loader2 className="w-3 h-3 animate-spin" />
                        </span>
                        <span>
                            {adaptiveMode
                                ? `Generating ${targetDifficulty}-level questions...`
                                : 'Generating questions with LLM...'}
                        </span>
                    </div>
                </div>

                <p className="text-xs text-gray-400">Topic: &ldquo;{activeTopic}&rdquo;</p>
                {adaptiveMode && (
                    <div className="mt-2 flex items-center gap-2">
                        <Zap className="w-3 h-3 text-blue-500" aria-hidden="true" />
                        <p className="text-xs text-blue-500">
                            Mastery: {Math.round(currentMastery * 100)}% &rarr; Target: {targetDifficulty}
                        </p>
                    </div>
                )}
            </div>
        );
    }

    if (!quiz) {
        return (
            <div className="max-w-md mx-auto bg-white p-8 rounded-lg shadow-md">
                <h2
                    ref={startHeadingRef}
                    tabIndex={-1}
                    className="text-2xl font-bold mb-6 text-center focus:outline-none"
                >
                    Start Assessment
                </h2>

                {/* Adaptive Mode Toggle */}
                <div className="mb-6 p-4 bg-gradient-to-r from-blue-50 to-indigo-50 rounded-lg border border-blue-100">
                    <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2">
                            <Zap className="w-5 h-5 text-blue-600" aria-hidden="true" />
                            <span id={ids.adaptiveLabel} className="font-medium text-gray-800">Adaptive Mode</span>
                        </div>
                        <button
                            type="button"
                            role="switch"
                            aria-checked={adaptiveMode}
                            aria-labelledby={ids.adaptiveLabel}
                            aria-describedby={ids.adaptiveHint}
                            onClick={() => setAdaptiveMode(!adaptiveMode)}
                            className={`relative w-12 h-6 rounded-full transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 ${
                                adaptiveMode ? 'bg-blue-600' : 'bg-gray-300'
                            }`}
                        >
                            <span
                                aria-hidden="true"
                                className={`absolute top-1 left-1 w-4 h-4 bg-white rounded-full transition-transform ${
                                    adaptiveMode ? 'translate-x-6' : 'translate-x-0'
                                }`}
                            />
                        </button>
                    </div>
                    <p id={ids.adaptiveHint} className="text-xs text-gray-600">
                        {adaptiveMode
                            ? 'Questions will be tailored to your current proficiency level'
                            : 'Questions will have mixed difficulty levels'}
                    </p>
                </div>

                {/* Topic Selection */}
                <div className="mb-4">
                    <label htmlFor={ids.topic} className="block text-sm font-medium text-gray-700 mb-2">Topic</label>
                    <select
                        id={ids.topic}
                        value={topic}
                        onChange={(e) => {
                            setTopic(e.target.value);
                            if (e.target.value !== CUSTOM_TOPIC) setCustomTopic('');
                        }}
                        className="w-full p-2 border border-blue-300 rounded-md focus:ring-2 focus:ring-blue-500"
                    >
                        {subjectTopics.map((t) => (
                            <option key={t.value} value={t.value}>{t.label}</option>
                        ))}
                        <option value={CUSTOM_TOPIC}>Custom topic...</option>
                    </select>
                    {topic === CUSTOM_TOPIC && (
                        <>
                            <label htmlFor={ids.customTopic} className="sr-only">Custom topic</label>
                            <input
                                id={ids.customTopic}
                                type="text"
                                value={customTopic}
                                onChange={(e) => setCustomTopic(e.target.value)}
                                placeholder="Enter a topic (e.g., Manifest Destiny)"
                                maxLength={MAX_TOPIC_LENGTH}
                                className="w-full mt-2 p-2 border border-blue-300 rounded-md focus:ring-2 focus:ring-blue-500"
                            />
                        </>
                    )}
                </div>

                {/* Current Mastery Display (when adaptive mode is on) */}
                {adaptiveMode && (
                    <div className="mb-6">
                        <MasteryIndicator
                            mastery={currentMastery}
                            targetDifficulty={targetDifficulty}
                            topic={selectedTopic || undefined}
                            showAdaptingMessage={true}
                        />
                    </div>
                )}

                {/* Error/Notice Banners */}
                <SyncNotice message={lastSyncError} />
                {formError && (
                    <div role="alert" className="mb-3 p-3 bg-red-50 border border-red-200 rounded-md flex items-center gap-2">
                        <AlertCircle className="w-4 h-4 text-red-500 flex-shrink-0" aria-hidden="true" />
                        <p className="text-sm text-red-700">{formError}</p>
                    </div>
                )}
                {resetStatus?.type === 'success' && (
                    <div role="status" className="mb-3 p-3 bg-green-50 border border-green-200 rounded-md flex items-center gap-2">
                        <CheckCircle className="w-4 h-4 text-green-500 flex-shrink-0" aria-hidden="true" />
                        <p className="text-sm text-green-700">Profile reset to initial state</p>
                    </div>
                )}
                {resetStatus?.type === 'error' && (
                    <div role="alert" className="mb-3 p-3 bg-red-50 border border-red-200 rounded-md flex items-center gap-2">
                        <AlertCircle className="w-4 h-4 text-red-500 flex-shrink-0" aria-hidden="true" />
                        <p className="text-sm text-red-700">
                            Could not reset your profile: {resetStatus.message}
                        </p>
                    </div>
                )}

                {/* Action Buttons */}
                <button
                    type="button"
                    onClick={handleStartQuiz}
                    disabled={isLoading}
                    className="w-full bg-blue-600 text-white py-3 rounded-md font-semibold hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition mb-3"
                >
                    {adaptiveMode ? 'Start Adaptive Assessment' : 'Generate Assessment'}
                </button>

                {/* Demo Reset Button */}
                <button
                    type="button"
                    onClick={handleResetProfile}
                    disabled={isResetting}
                    className="w-full flex items-center justify-center gap-2 text-gray-500 hover:text-gray-700 disabled:opacity-50 py-2 text-sm"
                >
                    <RefreshCw className={`w-4 h-4 ${isResetting ? 'animate-spin' : ''}`} aria-hidden="true" />
                    Reset Profile (Demo)
                </button>
            </div>
        );
    }

    const currentQ = quiz.questions?.[currentQuestionIndex];

    if (!currentQ) {
        return (
            <div className="max-w-md mx-auto bg-white p-8 rounded-lg shadow-md text-center" role="alert">
                <h3 className="text-lg font-semibold text-red-600 mb-2">Quiz Error</h3>
                <p className="text-gray-600 mb-4">Could not load quiz question. The quiz data may be invalid.</p>
                <button type="button" onClick={handleCloseResults} className="px-6 py-2 bg-blue-600 text-white rounded-md font-medium hover:bg-blue-700">
                    Try Again
                </button>
            </div>
        );
    }

    const isCorrect = selectedOption === currentQ.correct_option_id;
    const scoreRatio = score / quiz.questions?.length;

    return (
        <div className="max-w-2xl mx-auto">
            {/* Adaptation Banner (for adaptive quizzes) */}
            {isAdaptiveQuiz(quiz) && (
                <div className="mb-4">
                    <MasteryIndicator
                        mastery={currentMastery}
                        targetDifficulty={targetDifficulty}
                        topic={activeTopic}
                        showAdaptingMessage={true}
                        compact={false}
                    />
                </div>
            )}

            <SyncNotice message={lastSyncError} />

            {/* Progress */}
            <div className="mb-6 flex justify-between items-center text-sm text-gray-500">
                <span>Question {currentQuestionIndex + 1} of {quiz.questions?.length}</span>
                <div className="flex items-center gap-4">
                    <span>Score: {score}</span>
                    {isAdaptiveQuiz(quiz) && (
                        <MasteryIndicator
                            mastery={currentMastery}
                            targetDifficulty={targetDifficulty}
                            compact={true}
                        />
                    )}
                </div>
            </div>

            {/* Question Card */}
            <div className="bg-white rounded-xl shadow-lg overflow-hidden border border-gray-200">
                <div className="p-6 md:p-8">
                    <div className="flex items-start justify-between gap-4 mb-4">
                        <h3
                            ref={questionHeadingRef}
                            tabIndex={-1}
                            className="text-xl font-bold text-gray-900 focus:outline-none"
                        >
                            {currentQ.text}
                        </h3>
                        <DifficultyBadge difficulty={currentQ.difficulty} />
                    </div>

                    <div className="space-y-3">
                        {currentQ.options.map((opt) => {
                            const isSelected = opt.id === selectedOption;
                            const isCorrectOption = opt.id === currentQ.correct_option_id;
                            let btnClass = "w-full text-left p-4 rounded-lg border-2 transition-all ";
                            if (isSubmitted) {
                                if (isCorrectOption) {
                                    btnClass += "border-green-500 bg-green-50 text-green-700";
                                } else if (isSelected) {
                                    btnClass += "border-red-500 bg-red-50 text-red-700";
                                } else {
                                    btnClass += "border-gray-200 opacity-50";
                                }
                            } else {
                                btnClass += isSelected
                                    ? "border-blue-600 bg-blue-50 text-blue-700"
                                    : "border-gray-300 hover:border-blue-400 hover:bg-gray-50";
                            }

                            return (
                                <button
                                    key={opt.id}
                                    type="button"
                                    onClick={() => handleOptionSelect(opt.id)}
                                    disabled={isSubmitted}
                                    aria-pressed={isSubmitted ? undefined : isSelected}
                                    className={btnClass}
                                >
                                    <div className="flex items-center justify-between gap-3">
                                        <span className="flex items-center gap-3">
                                            {/* Shape, not just colour, shows the state of each option */}
                                            {isSubmitted && isCorrectOption ? (
                                                <CheckCircle className="w-5 h-5 flex-shrink-0 text-green-600" aria-hidden="true" />
                                            ) : isSubmitted && isSelected ? (
                                                <XCircle className="w-5 h-5 flex-shrink-0 text-red-600" aria-hidden="true" />
                                            ) : isSelected ? (
                                                <CircleDot className="w-5 h-5 flex-shrink-0 text-blue-600" aria-hidden="true" />
                                            ) : (
                                                <Circle className="w-5 h-5 flex-shrink-0 text-gray-400" aria-hidden="true" />
                                            )}
                                            <span>{opt.text}</span>
                                        </span>
                                        {isSubmitted && isCorrectOption && (
                                            <span className="text-xs font-semibold uppercase text-green-700">Correct answer</span>
                                        )}
                                        {isSubmitted && isSelected && !isCorrectOption && (
                                            <span className="text-xs font-semibold uppercase text-red-700">Your answer</span>
                                        )}
                                    </div>
                                </button>
                            );
                        })}
                    </div>
                </div>

                {/* Feedback / Remediation Section */}
                {isSubmitted && (
                    <div className={`p-6 border-t ${isCorrect ? "bg-green-50/50" : "bg-red-50/50"}`}>
                        <div className="flex gap-3">
                            <div className={`mt-1 ${isCorrect ? "text-green-600" : "text-red-600"}`} aria-hidden="true">
                                {isCorrect ? <CheckCircle className="w-6 h-6" /> : <BookOpen className="w-6 h-6" />}
                            </div>
                            <div className="flex-1">
                                <h4
                                    ref={feedbackHeadingRef}
                                    tabIndex={-1}
                                    className={`font-bold focus:outline-none ${isCorrect ? "text-green-800" : "text-red-800"}`}
                                >
                                    {isCorrect ? "Correct!" : "Concept Gap Identified"}
                                </h4>
                                <p className="text-gray-700 mt-1">{currentQ.explanation}</p>

                                {/* Mastery Update Feedback */}
                                {isAdaptiveQuiz(quiz) && (
                                    <div className="mt-3 p-3 bg-white/80 rounded-lg border border-gray-200">
                                        <p className="text-sm text-gray-600">
                                            <span className="font-medium">Mastery:</span>{' '}
                                            <span className={`font-medium ${isCorrect ? 'text-green-600' : 'text-red-600'}`}>
                                                {Math.round(currentMastery * 100)}%
                                            </span>
                                        </p>
                                    </div>
                                )}

                                {!isCorrect && (
                                    <div className="mt-4 p-4 bg-white rounded border border-red-200">
                                        <p className="text-xs uppercase font-bold text-gray-400 mb-1">Recommended Reading</p>
                                        <button
                                            type="button"
                                            onClick={() => handleAskTutor(currentQ.related_concept || activeTopic)}
                                            className="text-sm text-blue-600 hover:text-blue-800 underline text-left"
                                        >
                                            Ask the tutor about {currentQ.related_concept || activeTopic}
                                        </button>
                                    </div>
                                )}
                            </div>
                        </div>

                        <div className="mt-6 flex justify-end">
                            <button
                                type="button"
                                onClick={handleNextQuestion}
                                className="px-6 py-2 bg-blue-600 text-white rounded-md font-medium hover:bg-blue-700"
                            >
                                {currentQuestionIndex < quiz.questions?.length - 1 ? "Next Question" : "Finish Quiz"}
                            </button>
                        </div>
                    </div>
                )}

                {/* Action Button (Submit) */}
                {!isSubmitted && (
                    <div className="p-6 border-t bg-gray-50 flex justify-end">
                        <button
                            type="button"
                            onClick={handleSubmitAnswer}
                            disabled={!selectedOption}
                            className="px-6 py-2 bg-blue-600 text-white rounded-md font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                            Submit Answer
                        </button>
                    </div>
                )}
            </div>

            {/* Results Modal */}
            {showResults && (
                <Dialog
                    labelledBy={ids.results}
                    onClose={handleCloseResults}
                    panelClassName="bg-white rounded-2xl p-8 max-w-2xl w-full shadow-2xl transform animate-in fade-in zoom-in duration-300 max-h-[90vh] overflow-y-auto relative"
                >
                    {/* Close button */}
                    <button
                        type="button"
                        onClick={handleCloseResults}
                        className="absolute top-4 right-4 text-gray-400 hover:text-gray-600 transition-colors"
                        aria-label="Close results"
                    >
                        <X className="w-6 h-6" aria-hidden="true" />
                    </button>
                    {/* Score Circle */}
                    <div className="relative w-36 h-36 mx-auto mb-6">
                        <svg className="w-full h-full transform -rotate-90" aria-hidden="true">
                            <circle
                                cx="72"
                                cy="72"
                                r="64"
                                strokeWidth="10"
                                className="stroke-gray-200 fill-none"
                            />
                            <circle
                                cx="72"
                                cy="72"
                                r="64"
                                strokeWidth="10"
                                className={`fill-none transition-all duration-1000 ease-out ${
                                    scoreRatio >= 0.7
                                        ? 'stroke-green-500'
                                        : scoreRatio >= 0.4
                                        ? 'stroke-yellow-500'
                                        : 'stroke-red-500'
                                }`}
                                style={{
                                    strokeDasharray: 402,
                                    strokeDashoffset: 402 - (402 * scoreRatio),
                                    strokeLinecap: 'round',
                                }}
                            />
                        </svg>
                        <div className="absolute inset-0 flex flex-col items-center justify-center">
                            <Trophy aria-hidden="true" className={`w-8 h-8 mb-1 ${
                                scoreRatio >= 0.7
                                    ? 'text-green-500'
                                    : scoreRatio >= 0.4
                                    ? 'text-yellow-500'
                                    : 'text-red-500'
                            }`} />
                            <span className="text-3xl font-bold text-gray-900">
                                {Math.round(scoreRatio * 100)}%
                            </span>
                        </div>
                    </div>

                    {/* Score Summary */}
                    <div className="text-center mb-6">
                        <h3 id={ids.results} className="text-2xl font-bold text-gray-900 mb-2">
                            {scoreRatio >= 0.7
                                ? 'Great Job!'
                                : scoreRatio >= 0.4
                                ? 'Good Effort!'
                                : 'Keep Learning!'}
                        </h3>
                        <p className="text-gray-600">
                            You answered <span className="font-semibold text-blue-600">{score}</span> out of{' '}
                            <span className="font-semibold">{quiz.questions?.length}</span> questions correctly
                        </p>
                        <p className="text-sm text-gray-500 mt-2">
                            Topic: {activeTopic}
                        </p>

                        {/* Adaptive Quiz Results */}
                        {isAdaptiveQuiz(quiz) && (
                            <div className="mt-4 p-3 bg-gradient-to-r from-blue-50 to-indigo-50 rounded-lg border border-blue-100">
                                <div className="flex items-center justify-center gap-2 mb-2">
                                    <Zap className="w-4 h-4 text-blue-600" aria-hidden="true" />
                                    <span className="text-sm font-medium text-blue-800">Adaptive Learning</span>
                                </div>
                                <div className="text-sm text-gray-600">
                                    <p>Current Mastery: <span className="font-semibold">{Math.round(currentMastery * 100)}%</span></p>
                                    <p>Next Quiz Difficulty: <span className={`font-semibold ${
                                        targetDifficulty === 'easy' ? 'text-green-600' :
                                        targetDifficulty === 'medium' ? 'text-yellow-600' : 'text-red-600'
                                    }`}>{targetDifficulty.charAt(0).toUpperCase() + targetDifficulty.slice(1)}</span></p>
                                </div>
                            </div>
                        )}

                        {quiz.average_difficulty != null && !isAdaptiveQuiz(quiz) && (
                            <div className="mt-3 flex items-center justify-center gap-2 text-sm">
                                <span className="text-gray-500">Quiz Difficulty:</span>
                                <span className={`font-medium ${
                                    quiz.average_difficulty < 0.4 ? 'text-green-600' :
                                    quiz.average_difficulty < 0.65 ? 'text-yellow-600' : 'text-red-600'
                                }`}>
                                    {quiz.average_difficulty < 0.4 ? 'Easy' :
                                     quiz.average_difficulty < 0.65 ? 'Medium' : 'Hard'}
                                </span>
                                <span className="text-gray-400">
                                    ({Math.round(quiz.average_difficulty * 100)}%)
                                </span>
                            </div>
                        )}
                    </div>

                    {/* Actions */}
                    <div className="space-y-3">
                        <button
                            type="button"
                            onClick={handleViewLearningPath}
                            className="w-full flex items-center justify-center gap-2 px-6 py-3 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 transition-colors"
                        >
                            <MapPin className="w-5 h-5" aria-hidden="true" />
                            View Learning Path
                        </button>
                        <button
                            type="button"
                            onClick={handleCloseResults}
                            className="w-full flex items-center justify-center gap-2 px-6 py-3 bg-gray-100 text-gray-700 rounded-lg font-medium hover:bg-gray-200 transition-colors"
                        >
                            <RotateCcw className="w-5 h-5" aria-hidden="true" />
                            {isAdaptiveQuiz(quiz) ? 'Continue Learning (Next Level)' : 'Try Another Assessment'}
                        </button>
                    </div>

                    {/* Post-Quiz Recommendations */}
                    <PostQuizRecommendations
                        recommendations={recommendations.status === 'success' ? recommendations.data : null}
                        isLoading={recommendations.status === 'loading'}
                        error={recommendations.status === 'error' ? recommendations.message : null}
                        onRetry={fetchRecommendations}
                        onPractice={handlePracticeConcept}
                        onAskTutor={handleAskTutor}
                    />

                    {/* Learning Path */}
                    <div className="mt-6 border-t border-gray-200 pt-6">
                        <LearningPath
                            conceptName={activeTopic}
                            onConceptClick={(name) => handleAskTutor(name)}
                        />
                    </div>
                </Dialog>
            )}
        </div>
    );
}
