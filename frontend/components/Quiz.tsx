'use client';

import { useState } from 'react';
import { apiClient } from '@/lib/api-client'; // Assuming this exists or I'll use fetch directly for now
import { Loader2, CheckCircle, XCircle, BookOpen } from 'lucide-react';

interface QuizQuestion {
    id: string;
    text: string;
    options: { id: string; text: string }[];
    correct_option_id: string;
    explanation: string;
    source_chunk_id?: string;
}

interface Quiz {
    id: string;
    title: string;
    questions: QuizQuestion[];
}

export default function Quiz() {
    const [topic, setTopic] = useState('American Government');
    const [quiz, setQuiz] = useState<Quiz | null>(null);
    const [currentQuestionIndex, setCurrentQuestionIndex] = useState(0);
    const [selectedOption, setSelectedOption] = useState<string | null>(null);
    const [isSubmitted, setIsSubmitted] = useState(false);
    const [isLoading, setIsLoading] = useState(false);
    const [score, setScore] = useState(0);

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
        if (selectedOption === currentQ?.correct_option_id) {
            setScore(s => s + 1);
        }
    };

    const handleNextQuestion = () => {
        if (!quiz) return;
        if (currentQuestionIndex < quiz.questions.length - 1) {
            setCurrentQuestionIndex(prev => prev + 1);
            setSelectedOption(null);
            setIsSubmitted(false);
        } else {
            // Quiz finished
            alert(`Quiz Finished! Score: ${score + (selectedOption === quiz.questions[currentQuestionIndex].correct_option_id ? 0 : 0)}/${quiz.questions.length}`);
        }
    };

    if (isLoading) {
        return (
            <div className="flex flex-col items-center justify-center p-12">
                <Loader2 className="w-12 h-12 animate-spin text-primary-600 mb-4" />
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
                        className="w-full p-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-primary-500"
                    >
                        <option value="American Government">American Government</option>
                        <option value="US History">US History</option>
                        <option value="Citizenship Test">Citizenship Test</option>
                        <option value="Biology">Biology (Demo)</option>
                    </select>
                </div>
                <button
                    onClick={handleStartQuiz}
                    className="w-full bg-primary-600 text-white py-3 rounded-md font-semibold hover:bg-primary-700 transition"
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
                    <h3 className="text-xl font-bold text-gray-900 mb-6">{currentQ.text}</h3>

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
                                    ? "border-primary-600 bg-primary-50 text-primary-700"
                                    : "border-gray-200 hover:border-gray-300 hover:bg-gray-50";
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
                                className="px-6 py-2 bg-primary-600 text-white rounded-md font-medium hover:bg-primary-700"
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
                            className="px-6 py-2 bg-primary-600 text-white rounded-md font-medium hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                            Submit Answer
                        </button>
                    </div>
                )}
            </div>
        </div>
    );
}
