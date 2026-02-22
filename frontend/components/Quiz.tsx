'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { Loader2, CheckCircle, XCircle, BookOpen, Trophy, RotateCcw, MapPin, Zap, RefreshCw, AlertCircle } from 'lucide-react';
import { useAppStore } from '@/lib/store';
import MasteryIndicator from './MasteryIndicator';
import PostQuizRecommendations from './PostQuizRecommendations';
import LearningPath from './LearningPath';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const API_PREFIX = '/api/v1';

type Difficulty = 'easy' | 'medium' | 'hard';

interface QuizQuestion {
    id: string;
    text: string;
    options: { id: string; text: string }[];
    correct_option_id: string;
    explanation: string;
    source_chunk_id?: string;
    related_concept?: string;
    difficulty?: Difficulty;
    difficulty_score?: number;
}

interface QuestionResult {
    question_id: string;
    related_concept: string;
    correct: boolean;
}

interface RecommendationData {
    path_type: string;
    score_pct: number;
    remediation: any[];
    advancement: any[];
    summary: string;
}

interface Quiz {
    id: string;
    title: string;
    questions: QuizQuestion[];
    average_difficulty?: number;
}

interface AdaptiveQuiz extends Quiz {
    student_mastery: number;
    target_difficulty: Difficulty;
    adapted: boolean;
}

const DifficultyBadge = ({ difficulty }: { difficulty?: Difficulty }) => {
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
const SUBJECT_TOPICS: Record<string, { value: string; label: string }[]> = {
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

export default function Quiz() {
    const router = useRouter();
    const [topic, setTopic] = useState('The American Revolution');
    const [customTopic, setCustomTopic] = useState('');
    const [quiz, setQuiz] = useState<AdaptiveQuiz | Quiz | null>(null);
    const [currentQuestionIndex, setCurrentQuestionIndex] = useState(0);
    const [selectedOption, setSelectedOption] = useState<string | null>(null);
    const [isSubmitted, setIsSubmitted] = useState(false);
    const [isLoading, setIsLoading] = useState(false);
    const [score, setScore] = useState(0);
    const [showResults, setShowResults] = useState(false);

    // The actual topic being quizzed (resolved from dropdown or custom input)
    const [activeTopic, setActiveTopic] = useState('The American Revolution');

    // Adaptive mode state
    const [adaptiveMode, setAdaptiveMode] = useState(true);
    const [currentMastery, setCurrentMastery] = useState(0.3);
    const [targetDifficulty, setTargetDifficulty] = useState<Difficulty>('easy');

    // Post-quiz recommendations state
    const [questionResults, setQuestionResults] = useState<QuestionResult[]>([]);
    const [recommendations, setRecommendations] = useState<RecommendationData | null>(null);
    const [recsLoading, setRecsLoading] = useState(false);
    const [recsError, setRecsError] = useState<string | null>(null);

    // Inline error/notice state (replaces alert())
    const [formError, setFormError] = useState<string | null>(null);
    const [resetNotice, setResetNotice] = useState(false);

    // Get mastery tracking from store
    const {
        updateMastery,
        setHighlightedConcepts,
        loadMasteryFromBackend,
        resetMasteryOnBackend,
        getMastery,
        currentSubject
    } = useAppStore();

    // Get topics for the current subject
    const subjectTopics = SUBJECT_TOPICS[currentSubject] || DEFAULT_TOPICS;

    // Reset topic when subject changes
    useEffect(() => {
        const topics = SUBJECT_TOPICS[currentSubject] || DEFAULT_TOPICS;
        setTopic(topics[0].value);
        setCustomTopic('');
    }, [currentSubject]);

    // Load mastery from backend on mount
    useEffect(() => {
        loadMasteryFromBackend();
    }, [loadMasteryFromBackend]);

    // Update local mastery display when topic changes
    useEffect(() => {
        const displayTopic = topic === '__custom__' ? customTopic.trim() : topic;
        const mastery = getMastery(displayTopic || topic);
        setCurrentMastery(mastery);
        // Determine target difficulty
        if (mastery < 0.4) setTargetDifficulty('easy');
        else if (mastery <= 0.7) setTargetDifficulty('medium');
        else setTargetDifficulty('hard');
    }, [topic, customTopic, getMastery]);

    const handleStartQuiz = async () => {
        const effectiveTopic = topic === '__custom__' ? customTopic.trim() : topic;
        if (!effectiveTopic) {
            setFormError('Please enter a topic.');
            return;
        }
        setFormError(null);
        setActiveTopic(effectiveTopic);
        setIsLoading(true);
        try {
            let data;

            if (adaptiveMode) {
                // Use adaptive endpoint
                const res = await fetch(
                    `${API_BASE}${API_PREFIX}/quiz/generate-adaptive?topic=${encodeURIComponent(effectiveTopic)}&num_questions=3&subject=${encodeURIComponent(currentSubject)}`,
                    { method: 'POST' }
                );
                if (!res.ok) {
                    const errBody = await res.text();
                    throw new Error(`Quiz generation failed (${res.status}): ${errBody}`);
                }
                data = await res.json() as AdaptiveQuiz;

                // Update local state with backend's mastery info
                setCurrentMastery(data.student_mastery);
                setTargetDifficulty(data.target_difficulty);
            } else {
                // Use standard endpoint
                const res = await fetch(
                    `${API_BASE}${API_PREFIX}/quiz/generate?topic=${encodeURIComponent(effectiveTopic)}&num_questions=3&subject=${encodeURIComponent(currentSubject)}`,
                    { method: 'POST' }
                );
                if (!res.ok) {
                    const errBody = await res.text();
                    throw new Error(`Quiz generation failed (${res.status}): ${errBody}`);
                }
                data = await res.json() as Quiz;
            }

            if (!data.questions || data.questions.length === 0) {
                throw new Error('Quiz generated with no questions. Try a different topic.');
            }

            setQuiz(data);
            setCurrentQuestionIndex(0);
            setScore(0);
            setIsSubmitted(false);
            setSelectedOption(null);
        } catch (error) {
            console.error("Failed to generate quiz", error);
            setFormError("Failed to generate quiz. Please ensure the backend is running.");
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

        // Update mastery tracking for the topic (syncs to backend)
        updateMastery(activeTopic, isCorrect);

        // Update local mastery display
        const delta = isCorrect ? 0.15 : -0.1;
        const newMastery = Math.max(0.1, Math.min(1, currentMastery + delta));
        setCurrentMastery(newMastery);

        // Update target difficulty based on new mastery
        if (newMastery < 0.4) setTargetDifficulty('easy');
        else if (newMastery <= 0.7) setTargetDifficulty('medium');
        else setTargetDifficulty('hard');
    };

    const handleNextQuestion = () => {
        if (!quiz) return;
        if (currentQuestionIndex < quiz.questions.length - 1) {
            setCurrentQuestionIndex(prev => prev + 1);
            setSelectedOption(null);
            setIsSubmitted(false);
        } else {
            // Quiz finished - show results modal
            setShowResults(true);
            // Fetch recommendations asynchronously
            fetchRecommendations();
        }
    };

    const fetchRecommendations = async () => {
        setRecsLoading(true);
        setRecsError(null);
        try {
            const res = await fetch(`${API_BASE}${API_PREFIX}/quiz/recommendations`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    topic: activeTopic,
                    question_results: questionResults,
                    student_id: 'default',
                    subject: currentSubject,
                }),
            });
            if (!res.ok) {
                throw new Error(`Failed to fetch recommendations (${res.status})`);
            }
            const data = await res.json();
            setRecommendations(data);
        } catch (err) {
            console.error('Failed to fetch recommendations:', err);
            setRecsError('Unable to load recommendations. Your score and results are still available above.');
        } finally {
            setRecsLoading(false);
        }
    };

    const handleRetry = () => {
        setQuiz(null);
        setShowResults(false);
        setCurrentQuestionIndex(0);
        setScore(0);
        setSelectedOption(null);
        setIsSubmitted(false);
        setQuestionResults([]);
        setRecommendations(null);
        setRecsError(null);
        setFormError(null);
    };

    const handleResetProfile = async () => {
        await resetMasteryOnBackend();
        setCurrentMastery(0.3);
        setTargetDifficulty('easy');
        setResetNotice(true);
        setTimeout(() => setResetNotice(false), 3000);
    };

    const handleViewLearningPath = () => {
        // Set highlighted concepts before navigating to graph
        setHighlightedConcepts([activeTopic]);
        router.push('/graph');
    };

    const handlePracticeConcept = (concept: string) => {
        handleRetry();
        setTopic(concept);
    };

    const handleAskTutor = (concept: string) => {
        router.push(`/chat?question=${encodeURIComponent(`Explain ${concept}`)}`);
    };

    // Check if quiz is adaptive
    const isAdaptiveQuiz = (q: Quiz | AdaptiveQuiz | null): q is AdaptiveQuiz => {
        return q !== null && 'adapted' in q && q.adapted === true;
    };

    if (isLoading) {
        return (
            <div className="flex flex-col items-center justify-center p-12">
                {/* Animated quiz generation indicator */}
                <div className="relative mb-6">
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
                        <span className="w-5 h-5 rounded-full bg-green-100 text-green-600 flex items-center justify-center text-xs">
                            <CheckCircle className="w-3 h-3" />
                        </span>
                        <span>Retrieving context from knowledge graph</span>
                    </div>
                    <div className="flex items-center gap-2">
                        <span className="w-5 h-5 rounded-full bg-blue-100 text-blue-600 flex items-center justify-center">
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
                        <Zap className="w-3 h-3 text-blue-500" />
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
                <h2 className="text-2xl font-bold mb-6 text-center">Start Assessment</h2>

                {/* Adaptive Mode Toggle */}
                <div className="mb-6 p-4 bg-gradient-to-r from-blue-50 to-indigo-50 rounded-lg border border-blue-100">
                    <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2">
                            <Zap className="w-5 h-5 text-blue-600" />
                            <span className="font-medium text-gray-800">Adaptive Mode</span>
                        </div>
                        <button
                            onClick={() => setAdaptiveMode(!adaptiveMode)}
                            className={`relative w-12 h-6 rounded-full transition-colors ${
                                adaptiveMode ? 'bg-blue-600' : 'bg-gray-300'
                            }`}
                        >
                            <span
                                className={`absolute top-1 left-1 w-4 h-4 bg-white rounded-full transition-transform ${
                                    adaptiveMode ? 'translate-x-6' : 'translate-x-0'
                                }`}
                            />
                        </button>
                    </div>
                    <p className="text-xs text-gray-600">
                        {adaptiveMode
                            ? 'Questions will be tailored to your current proficiency level'
                            : 'Questions will have mixed difficulty levels'}
                    </p>
                </div>

                {/* Topic Selection */}
                <div className="mb-4">
                    <label className="block text-sm font-medium text-gray-700 mb-2">Topic</label>
                    <select
                        value={topic}
                        onChange={(e) => {
                            setTopic(e.target.value);
                            if (e.target.value !== '__custom__') setCustomTopic('');
                        }}
                        className="w-full p-2 border border-blue-300 rounded-md focus:ring-2 focus:ring-blue-500"
                    >
                        {subjectTopics.map((t) => (
                            <option key={t.value} value={t.value}>{t.label}</option>
                        ))}
                        <option value="__custom__">Custom topic...</option>
                    </select>
                    {topic === '__custom__' && (
                        <input
                            type="text"
                            value={customTopic}
                            onChange={(e) => setCustomTopic(e.target.value)}
                            placeholder="Enter a topic (e.g., Manifest Destiny)"
                            className="w-full mt-2 p-2 border border-blue-300 rounded-md focus:ring-2 focus:ring-blue-500"
                        />
                    )}
                </div>

                {/* Current Mastery Display (when adaptive mode is on) */}
                {adaptiveMode && (
                    <div className="mb-6">
                        <MasteryIndicator
                            mastery={currentMastery}
                            targetDifficulty={targetDifficulty}
                            topic={topic}
                            showAdaptingMessage={true}
                        />
                    </div>
                )}

                {/* Error/Notice Banners */}
                {formError && (
                    <div className="mb-3 p-3 bg-red-50 border border-red-200 rounded-md flex items-center gap-2">
                        <AlertCircle className="w-4 h-4 text-red-500 flex-shrink-0" />
                        <p className="text-sm text-red-700">{formError}</p>
                    </div>
                )}
                {resetNotice && (
                    <div className="mb-3 p-3 bg-green-50 border border-green-200 rounded-md flex items-center gap-2">
                        <CheckCircle className="w-4 h-4 text-green-500 flex-shrink-0" />
                        <p className="text-sm text-green-700">Profile reset to initial state</p>
                    </div>
                )}

                {/* Action Buttons */}
                <button
                    onClick={handleStartQuiz}
                    className="w-full bg-blue-600 text-white py-3 rounded-md font-semibold hover:bg-blue-700 transition mb-3"
                >
                    {adaptiveMode ? 'Start Adaptive Assessment' : 'Generate Assessment'}
                </button>

                {/* Demo Reset Button */}
                <button
                    onClick={handleResetProfile}
                    className="w-full flex items-center justify-center gap-2 text-gray-500 hover:text-gray-700 py-2 text-sm"
                >
                    <RefreshCw className="w-4 h-4" />
                    Reset Profile (Demo)
                </button>
            </div>
        );
    }

    const currentQ = quiz.questions?.[currentQuestionIndex];

    if (!currentQ) {
        return (
            <div className="max-w-md mx-auto bg-white p-8 rounded-lg shadow-md text-center">
                <h3 className="text-lg font-semibold text-red-600 mb-2">Quiz Error</h3>
                <p className="text-gray-600 mb-4">Could not load quiz question. The quiz data may be invalid.</p>
                <button onClick={handleRetry} className="px-6 py-2 bg-blue-600 text-white rounded-md font-medium hover:bg-blue-700">
                    Try Again
                </button>
            </div>
        );
    }

    const isCorrect = selectedOption === currentQ.correct_option_id;

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

            {/* Progress */}
            <div className="mb-6 flex justify-between items-center text-sm text-gray-500">
                <span>Question {currentQuestionIndex + 1} of {quiz.questions.length}</span>
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
                        <h3 className="text-xl font-bold text-gray-900">{currentQ.text}</h3>
                        <DifficultyBadge difficulty={currentQ.difficulty} />
                    </div>

                    <div className="space-y-3">
                        {currentQ.options.map((opt) => {
                            let btnClass = "w-full text-left p-4 rounded-lg border-2 transition-all ";
                            if (isSubmitted) {
                                if (opt.id === currentQ.correct_option_id) {
                                    btnClass += "border-green-500 bg-green-50 text-green-700";
                                } else if (opt.id === selectedOption) {
                                    btnClass += "border-red-500 bg-red-50 text-red-700";
                                } else {
                                    btnClass += "border-gray-200 opacity-50";
                                }
                            } else {
                                btnClass += selectedOption === opt.id
                                    ? "border-blue-600 bg-blue-50 text-blue-700"
                                    : "border-gray-300 hover:border-blue-400 hover:bg-gray-50";
                            }

                            return (
                                <button
                                    key={opt.id}
                                    onClick={() => handleOptionSelect(opt.id)}
                                    disabled={isSubmitted}
                                    className={btnClass}
                                >
                                    <div className="flex items-center justify-between">
                                        <span>{opt.text}</span>
                                        {isSubmitted && opt.id === currentQ.correct_option_id && <CheckCircle className="w-5 h-5 text-green-600" />}
                                        {isSubmitted && opt.id === selectedOption && opt.id !== currentQ.correct_option_id && <XCircle className="w-5 h-5 text-red-600" />}
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
                            <div className={`mt-1 ${isCorrect ? "text-green-600" : "text-red-600"}`}>
                                {isCorrect ? <CheckCircle className="w-6 h-6" /> : <BookOpen className="w-6 h-6" />}
                            </div>
                            <div className="flex-1">
                                <h4 className={`font-bold ${isCorrect ? "text-green-800" : "text-red-800"}`}>
                                    {isCorrect ? "Correct!" : "Concept Gap Identified"}
                                </h4>
                                <p className="text-gray-700 mt-1">{currentQ.explanation}</p>

                                {/* Mastery Update Feedback */}
                                {isAdaptiveQuiz(quiz) && (
                                    <div className="mt-3 p-3 bg-white/80 rounded-lg border border-gray-200">
                                        <p className="text-sm text-gray-600">
                                            <span className="font-medium">Mastery updated:</span>{' '}
                                            <span className={isCorrect ? 'text-green-600' : 'text-red-600'}>
                                                {isCorrect ? '+15%' : '-10%'}
                                            </span>
                                            {' '}&rarr;{' '}
                                            <span className="font-medium">{Math.round(currentMastery * 100)}%</span>
                                        </p>
                                    </div>
                                )}

                                {!isCorrect && (
                                    <div className="mt-4 p-4 bg-white rounded border border-red-200">
                                        <p className="text-xs uppercase font-bold text-gray-400 mb-1">Recommended Reading</p>
                                        <p className="text-sm text-gray-800 italic">"Refer to section on {activeTopic}..."</p>
                                    </div>
                                )}
                            </div>
                        </div>

                        <div className="mt-6 flex justify-end">
                            <button
                                onClick={handleNextQuestion}
                                className="px-6 py-2 bg-blue-600 text-white rounded-md font-medium hover:bg-blue-700"
                            >
                                {currentQuestionIndex < quiz.questions.length - 1 ? "Next Question" : "Finish Quiz"}
                            </button>
                        </div>
                    </div>
                )}

                {/* Action Button (Submit) */}
                {!isSubmitted && (
                    <div className="p-6 border-t bg-gray-50 flex justify-end">
                        <button
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
            {showResults && quiz && (
                <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
                    <div className="bg-white rounded-2xl p-8 max-w-2xl w-full shadow-2xl transform animate-in fade-in zoom-in duration-300 max-h-[90vh] overflow-y-auto">
                        {/* Score Circle */}
                        <div className="relative w-36 h-36 mx-auto mb-6">
                            <svg className="w-full h-full transform -rotate-90">
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
                                        score / quiz.questions.length >= 0.7
                                            ? 'stroke-green-500'
                                            : score / quiz.questions.length >= 0.4
                                            ? 'stroke-yellow-500'
                                            : 'stroke-red-500'
                                    }`}
                                    style={{
                                        strokeDasharray: 402,
                                        strokeDashoffset: 402 - (402 * score / quiz.questions.length),
                                        strokeLinecap: 'round',
                                    }}
                                />
                            </svg>
                            <div className="absolute inset-0 flex flex-col items-center justify-center">
                                <Trophy className={`w-8 h-8 mb-1 ${
                                    score / quiz.questions.length >= 0.7
                                        ? 'text-green-500'
                                        : score / quiz.questions.length >= 0.4
                                        ? 'text-yellow-500'
                                        : 'text-red-500'
                                }`} />
                                <span className="text-3xl font-bold text-gray-900">
                                    {Math.round((score / quiz.questions.length) * 100)}%
                                </span>
                            </div>
                        </div>

                        {/* Score Summary */}
                        <div className="text-center mb-6">
                            <h3 className="text-2xl font-bold text-gray-900 mb-2">
                                {score / quiz.questions.length >= 0.7
                                    ? 'Great Job!'
                                    : score / quiz.questions.length >= 0.4
                                    ? 'Good Effort!'
                                    : 'Keep Learning!'}
                            </h3>
                            <p className="text-gray-600">
                                You answered <span className="font-semibold text-blue-600">{score}</span> out of{' '}
                                <span className="font-semibold">{quiz.questions.length}</span> questions correctly
                            </p>
                            <p className="text-sm text-gray-500 mt-2">
                                Topic: {activeTopic}
                            </p>

                            {/* Adaptive Quiz Results */}
                            {isAdaptiveQuiz(quiz) && (
                                <div className="mt-4 p-3 bg-gradient-to-r from-blue-50 to-indigo-50 rounded-lg border border-blue-100">
                                    <div className="flex items-center justify-center gap-2 mb-2">
                                        <Zap className="w-4 h-4 text-blue-600" />
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

                            {quiz.average_difficulty !== undefined && !isAdaptiveQuiz(quiz) && (
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
                                onClick={handleViewLearningPath}
                                className="w-full flex items-center justify-center gap-2 px-6 py-3 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 transition-colors"
                            >
                                <MapPin className="w-5 h-5" />
                                View Learning Path
                            </button>
                            <button
                                onClick={handleRetry}
                                className="w-full flex items-center justify-center gap-2 px-6 py-3 bg-gray-100 text-gray-700 rounded-lg font-medium hover:bg-gray-200 transition-colors"
                            >
                                <RotateCcw className="w-5 h-5" />
                                {isAdaptiveQuiz(quiz) ? 'Continue Learning (Next Level)' : 'Try Another Assessment'}
                            </button>
                        </div>

                        {/* Post-Quiz Recommendations */}
                        <PostQuizRecommendations
                            recommendations={recommendations}
                            isLoading={recsLoading}
                            error={recsError}
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
                    </div>
                </div>
            )}
        </div>
    );
}
