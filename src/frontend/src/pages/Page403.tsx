import React from 'react';

export default function Page403() {
    return (
        <div className="fixed left-0 top-0 z-50 flex h-full w-full items-center justify-center bg-black bg-opacity-70">
            <div className="flex w-[90%] max-w-lg text-center min-h-[200px] flex-col justify-center rounded-lg p-8 shadow-xl bg-gray-50">
                <h1 className="mb-4 text-4xl font-bold text-red-600">
                    403
                </h1>
                <p className="mb-8 text-lg text-gray-800">
                    您无权访问该页面
                </p>
                <div className="flex justify-center">
                    <button
                        className="rounded bg-blue-500 px-6 py-2 text-sm font-semibold hover:bg-blue-600 text-gray-50"
                        onClick={() => window.location.href = __APP_ENV__.BASE_URL + '/'}
                    >
                        返回首页
                    </button>
                </div>
            </div>
        </div>
    );
};
