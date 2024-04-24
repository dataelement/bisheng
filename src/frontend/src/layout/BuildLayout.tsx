import { NavLink, Outlet } from "react-router-dom";

export default function BuildLayout(params) {

    return <div className="bg-[#F4F5F8]">
        <div className="build-tab flex justify-center h-[60px] items-center border-b relative top-[-60px]">
            <div className="px-20"><NavLink to={'assist'}>助手</NavLink></div>
            <div className="px-20"><NavLink to={'skills'}>技能</NavLink></div>
            {/* <div className="px-20"><NavLink to={'tools'}>工具</NavLink></div> */}
        </div>
        <div className="" style={{ height: 'calc(100vh - 125px)' }}>
            <Outlet />
        </div>
    </div>
};
