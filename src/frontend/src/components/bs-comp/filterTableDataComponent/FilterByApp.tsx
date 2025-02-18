import MultiSelect from "@/components/bs-ui/select/multi";
import { getOperatorsApi } from "@/controllers/API/log";
import { useState, useRef } from "react";

export default function FilterByApp({ value, onChange }) {
    const { apps, loadApps, searchApp } = useApps();

    return (
        <div className="w-[200px] relative">
            <MultiSelect
                contentClassName="overflow-y-auto max-w-[200px]"
                options={apps}
                value={value}
                multiple
                placeholder="应用名称"
                onLoad={loadApps}
                onSearch={searchApp}
                onChange={onChange}
            />
        </div>
    );
}

const useApps = () => {
    const [apps, setApps] = useState<any[]>([]);
    const appRef = useRef<any[]>([]);

    // Load apps from the API and store in state
    const loadApps = async () => {
        try {
            const res = await getOperatorsApi();
            const options = res.map((a: any) => ({
                label: a.app_name, // Changed to 'app_name'
                value: a.app_id,   // Changed to 'app_id'
            }));
            appRef.current = options;
            setApps(options);
        } catch (error) {
            console.error("Error loading apps:", error);
            // Optionally, you can set apps to an empty array or show an error message
        }
    };

    // Search apps from the API
    const searchApp = async (name: string) => {
        try {
            const res = await getOperatorsApi({ search: name });
            const options = res.map((a: any) => ({
                label: a.app_name, // Changed to 'app_name'
                value: a.app_id,   // Changed to 'app_id'
            }));
            appRef.current = options;
            setApps(options);
        } catch (error) {
            console.error("Error searching apps:", error);
            // Optionally, handle the error by clearing the list or showing a message
        }
    };

    return {
        apps,
        loadApps,
        searchApp,
    };
};
