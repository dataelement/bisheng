export default function Separator({ className = '', text }) {
    
    return <div className={'flex items-center justify-center py-4 text-gray-400 text-sm ' + className}>
        ----------- {text} -----------
    </div>
};
