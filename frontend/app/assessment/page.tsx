'use client';

import { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import { Loader2 } from 'lucide-react';
import Quiz from '@/components/Quiz';
import SubjectPicker from '@/components/SubjectPicker';

/** The quiz, with the topic from `?topic=` (e.g. "Practice" on a learning path) preselected. */
function AssessmentQuiz() {
    const searchParams = useSearchParams();
    const topic = searchParams.get('topic')?.trim() || undefined;
    return <Quiz initialTopic={topic} />;
}

export default function AssessmentPage() {
    return (
        <div className="min-h-screen bg-gray-50">
            {/* Header */}
            <header className="bg-white shadow-sm border-b border-gray-200">
                <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
                    <div className="flex flex-wrap items-center justify-between gap-4">
                        <div>
                            <h1 className="text-3xl font-extrabold text-gray-900">
                                Adaptive Assessment Engine
                            </h1>
                            <p className="mt-2 text-gray-600">
                                Generated dynamically from trusted knowledge sources
                            </p>
                        </div>
                        <SubjectPicker />
                    </div>
                </div>
            </header>

            {/* Main Content */}
            <main id="main-content" className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
                <Suspense
                    fallback={
                        <div className="flex justify-center p-12" role="status">
                            <Loader2 className="w-8 h-8 animate-spin text-blue-600" aria-hidden="true" />
                            <span className="sr-only">Loading assessment</span>
                        </div>
                    }
                >
                    <AssessmentQuiz />
                </Suspense>
            </main>
        </div>
    );
}
