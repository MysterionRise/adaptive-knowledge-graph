'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Loader2, CheckCircle, XCircle, BookOpen, Trophy, RotateCcw, MapPin } from 'lucide-react';
import { useAppStore } from '@/lib/store';

type Difficulty = 'easy' | 'medium' | 'hard';

interface QuizQuestion {
    id: string;
    text: string;
    options: { id: string; text: string }[];
    correct_option_id: string;
    explanation: string;
    source_chunk_id?: string;
    difficulty?: Difficulty;
    difficulty_score?: number;
}

interface Quiz {
    id: string;
    title: string;
    questions: QuizQuestion[];
    average_difficulty?: number;
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

export default function Quiz() {
    const router = useRouter();
    const [topic, setTopic] = useState('The American Revolution');
    const [quiz, setQuiz] = useState<Quiz | null>(null);
    const [currentQuestionIndex, setCurrentQuestionIndex] = useState(0);
    const [selectedOption, setSelectedOption] = useState<string | null>(null);
    const [isSubmitted, setIsSubmitted] = useState(false);
    const [isLoading, setIsLoading] = useState(false);
    const [score, setScore] = useState(0);
    const [showResults, setShowResults] = useState(false);

    // Get mastery tracking from store
    const { updateMastery, setHighlightedConcepts } = useAppStore();

    const handleStartQuiz = async () => {
        setIsLoading(true);
        try {
            // Direct fetch if apiClient doesn't have the method yet
            const res = await fetch(`/api/v1/quiz/generate?topic=${encodeURIComponent(topic)}&num_questions=3`, {
                method: 'POST'
            });
            const data = await res.json();
            setQuiz(data);
            setCurrentQuestionIndex(0);
            setScore(0);
            setIsSubmitted(false);
            setSelectedOption(null);
        } catch (error) {
            console.error("Failed to generate quiz", error);
            alert("Failed to generate quiz. Ensure backend is running.");
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

        // Update mastery tracking for the topic
        updateMastery(topic, isCorrect);
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
        }
    };

    const handleRetry = () => {
        setQuiz(null);
        setShowResults(false);
        setCurrentQuestionIndex(0);
        setScore(0);
        setSelectedOption(null);
        setIsSubmitted(false);
    };

    const handleViewLearningPath = () => {
        // Set highlighted concepts before navigating to graph
        setHighlightedConcepts([topic]);
        router.push('/graph');
    };

    if (isLoading) {
        return (
            <div className="flex flex-col items-center justify-center p-12">
                <Loader2 className="w-12 h-12 animate-spin text-blue-600 mb-4" />
                <p className="text-gray-600">Generating adaptive quiz from knowledge graph...</p>
                <p className="text-xs text-gray-400 mt-2">Thinking about "{topic}"</p>
            </div>
        );
    }

    if (!quiz) {
        return (
            <div className="max-w-md mx-auto bg-white p-8 rounded-lg shadow-md">
                <h2 className="text-2xl font-bold mb-6 text-center">Start Assessment</h2>
                <div className="mb-4">
                    <label className="block text-sm font-medium text-gray-700 mb-2">Topic</label>
                    <select
                        value={topic}
                        onChange={(e) => setTopic(e.target.value)}
                        className="w-full p-2 border border-blue-300 rounded-md focus:ring-2 focus:ring-blue-500"
                    >
                        <option value="The American Revolution">The American Revolution</option>
                        <option value="The Constitution">The Constitution</option>
                        <option value="The Civil War">The Civil War</option>
                        <option value="Industrialization">Industrialization</option>
                        <option value="World War II">World War II</option>
                    </select>
                </div>
                <button
                    onClick={handleStartQuiz}
                    className="w-full bg-blue-600 text-white py-3 rounded-md font-semibold hover:bg-blue-700 transition"
                >
                    Generate Assessment
                </button>
            </div>
        );
    }

    const currentQ = quiz.questions[currentQuestionIndex];
    const isCorrect = selectedOption === currentQ.correct_option_id;

    return (
        <div className="max-w-2xl mx-auto">
            {/* Progress */}
            <div className="mb-6 flex justify-between items-center text-sm text-gray-500">
                <span>Question {currentQuestionIndex + 1} of {quiz.questions.length}</span>
                <span>Score: {score}</span>
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
                            <div>
                                <h4 className={`font-bold ${isCorrect ? "text-green-800" : "text-red-800"}`}>
                                    {isCorrect ? "Correct!" : "Concept Gap Detailed"}
                                </h4>
                                <p className="text-gray-700 mt-1">{currentQ.explanation}</p>

                                {!isCorrect && (
                                    <div className="mt-4 p-4 bg-white rounded border border-red-200">
                                        <p className="text-xs uppercase font-bold text-gray-400 mb-1">Recommended Reading</p>
                                        <p className="text-sm text-gray-800 italic">"Refer to section on {topic}..."</p>
                                        {/* In a real app, fetch the content chunk here */}
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
                    <div className="bg-white rounded-2xl p-8 max-w-md w-full shadow-2xl transform animate-in fade-in zoom-in duration-300">
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
                                Topic: {topic}
                            </p>
                            {quiz.average_difficulty !== undefined && (
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
                                Try Another Assessment
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
