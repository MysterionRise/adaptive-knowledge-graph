'use client';

import { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import { Loader2 } from 'lucide-react';
import PageHeader from '@/components/PageHeader';
import Quiz from '@/components/Quiz';

/** The quiz, with the topic from `?topic=` (e.g. "Practice" on a learning path) preselected. */
function AssessmentQuiz() {
    const searchParams = useSearchParams();
    const topic = searchParams.get('topic')?.trim() || undefined;
    return <Quiz initialTopic={topic} />;
}

export default function AssessmentPage() {
    return (
        <>
            <PageHeader title="Adaptive Assessment Engine" />

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
        </>
    );
}
