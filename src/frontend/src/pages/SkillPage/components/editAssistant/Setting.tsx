import { TitleIconBg } from "@/components/bs-comp/cardComponent";
import ContentSecuritySheet from "@/components/bs-comp/sheets/ContentSecuritySheet";
import SkillSheet from "@/components/bs-comp/sheets/SkillSheet";
import ToolsSheet from "@/components/bs-comp/sheets/ToolsSheet";
import { SettingIcon } from "@/components/bs-icons/setting";
import { ToolIcon } from "@/components/bs-icons/tool";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/bs-ui/accordion";
import { Button } from "@/components/bs-ui/button";
import { InputList, Textarea } from "@/components/bs-ui/input";
import { Switch } from "@/components/bs-ui/switch";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/bs-ui/tooltip";
import { useAssistantStore } from "@/store/assistantStore";
import {
  MinusCircledIcon,
  PlusCircledIcon,
  PlusIcon,
  QuestionMarkCircledIcon,
  ReloadIcon,
} from "@radix-ui/react-icons";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import ContentShow from "../ContentShow";
import KnowledgeBaseMulti from "./KnowledgeBaseMulti";
import ModelSelect from "./ModelSelect";
import Temperature from "./Temperature";
import KnowledgeSelect from "@/components/bs-comp/selectKnowledge";

export default function Setting() {
  const { t } = useTranslation();

  let { assistantState, dispatchAssistant } = useAssistantStore();
  if(!assistantState.content_security) {
    assistantState = {...assistantState, content_security:{
      open: true,
      reviewType: '敏感词表匹配',
      vocabularyType: ['内置词表','自定义词表'],
      vocabularyInput: '歧视\n色情\n暴力\n战争',
      automaticReply: '您的输入带有敏感词汇，我拒绝回答'}}
  } // 测试数据暂时修改，后期替换
  
  const [show, setShow] = useState(false)
  const [toggle,setToggle] = useState(assistantState.content_security.open)

  const checkedChange = (value) => {
    setToggle(value)
    setShow(value)
  }

  return (
    <div
      id="skill-scroll"
      className="h-full w-[50%] overflow-y-auto scrollbar-hide"
    >
      <h1 className="border bg-gray-50 indent-4 text-sm leading-8 text-muted-foreground">
        {t("build.basicConfiguration")}
      </h1>
      <Accordion type="multiple" className="w-full">
        {/* 基础配置 */}
        <AccordionItem value="item-1">
          <AccordionTrigger>
            <span>{t("build.modelConfiguration")}</span>
          </AccordionTrigger>
          <AccordionContent className="py-2">
            <div className="mb-4 px-6">
              <label htmlFor="model" className="bisheng-label">
                {t("build.model")}
              </label>
              <ModelSelect
                value={assistantState.model_name}
                onChange={(val) =>
                  dispatchAssistant("setting", { model_name: val })
                }
              />
            </div>
            <div className="mb-4 px-6">
              <label htmlFor="slider" className="bisheng-label">
                {t("build.temperature")}
              </label>
              <Temperature
                value={assistantState.temperature}
                onChange={(val) =>
                  dispatchAssistant("setting", { temperature: val })
                }
              ></Temperature>
            </div>
          </AccordionContent>
        </AccordionItem>
        {/* 开场引导 */}
        <AccordionItem value="item-2">
          <AccordionTrigger>
            <span>{t("build.openingIntroduction")}</span>
          </AccordionTrigger>
          <AccordionContent className="py-2">
            <div className="mb-4 px-6">
              <label htmlFor="open" className="bisheng-label">
                {t("build.openingStatement")}
              </label>
              <Textarea
                name="open"
                className="mt-2 min-h-[34px]"
                style={{ height: 56 }}
                placeholder={t("build.assistantMessageFormat")}
                value={assistantState.guide_word}
                onChange={(e) =>
                  dispatchAssistant("setting", { guide_word: e.target.value })
                }
              ></Textarea>
              {assistantState.guide_word.length > 1000 && (
                <p className="bisheng-tip mt-1">
                  {t("build.maximumPromptLength")}
                </p>
              )}
            </div>
            <div className="mb-4 px-6">
              <label htmlFor="open" className="bisheng-label flex gap-1">
                {t("build.guidingQuestions")}
                <TooltipProvider delayDuration={200}>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <QuestionMarkCircledIcon />
                    </TooltipTrigger>
                    <TooltipContent>
                      <p>{t("build.recommendQuestionsForUsers")}</p>
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </label>
              <InputList
                rules={[{ maxLength: 50, message: t("build.maxCharacters50") }]}
                value={assistantState.guide_question}
                onChange={(list) => {
                  dispatchAssistant("setting", { guide_question: list });
                }}
                placeholder={t("build.enterGuidingQuestions")}
              ></InputList>
            </div>
          </AccordionContent>
        </AccordionItem>
        {/* 内容安全审查 */}
        <AccordionItem value="item-3">
          <AccordionTrigger>
            <div className="flex flex-1 items-center justify-between">
              <span>内容安全审查</span>
              <div className="h-[20px] flex items-center">
                <ContentSecuritySheet data={assistantState.content_security} isOpen={show} 
                onSave={(data) => {dispatchAssistant('setContentSecurity',{
                  content_security: {...assistantState.content_security, ...data}
                }); console.log(assistantState)}}
                onCloseSheet={() => setShow(false)}>
                  {toggle && <SettingIcon onClick={(e) => {e.stopPropagation(); setShow(!show)}} className="w-[40px] h-[40px]"/>}
                </ContentSecuritySheet>
                <Switch className="mx-4" onClick={(e) => e.stopPropagation()} checked={toggle} 
                onCheckedChange={checkedChange}/>
              </div>
            </div>
          </AccordionTrigger>
          {toggle && <AccordionContent className="mb-[-16px]">
            <ContentShow data={assistantState.content_security}/>
          </AccordionContent>}
        </AccordionItem>
      </Accordion>
      <div className="text-center text-sm bg-[white] text-muted-foreground">通过敏感词表或 API 对会话内容进行安全审查</div>
      <h1 className="border-b bg-gray-50 indent-4 text-sm leading-8 text-muted-foreground">
        {t("build.knowledge")}
      </h1>
      <Accordion type="multiple" className="w-full">
        {/* 知识库 */}
        <AccordionItem value="item-1">
          <AccordionTrigger>
            <div className="flex flex-1 items-center justify-between">
              <span>{t("build.knowledgeBase")}</span>
              {/* <Popover>
              <PopoverTrigger asChild className="group">
                  <Button variant="link" size="sm"><TriangleRightIcon className="group-data-[state=open]:rotate-90" /> {t('build.autoCall')}</Button>
              </PopoverTrigger>
              <PopoverContent className="w-[560px]">
                  <div className="flex justify-between">
                      <label htmlFor="model" className="bisheng-label">{t('build.callingMethod')}</label>
                      <div>
                          <RadioCard checked={false} title={t('build.autoCall')} description={t('build.autoCallDescription')} calssName="mb-4"></RadioCard>
                          <RadioCard checked title={t('build.onDemandCall')} description={t('build.onDemandCallDescription')} calssName="mt-4"></RadioCard>
                      </div>
                  </div>
              </PopoverContent>
          </Popover> */}
            </div>
          </AccordionTrigger>
          <AccordionContent className="py-2">
            <div className="mb-4 px-6">
              <div className="flex gap-4">
                <KnowledgeSelect
                  multiple
                  value={assistantState.knowledge_list.map(el => ({ label: el.name, value: el.id }))}
                  onChange={(vals) =>
                    dispatchAssistant("setting", { knowledge_list: vals.map(el => ({ name: el.label, id: el.value })) })
                  }
                >
                  {(reload) => (
                    <div className="flex justify-between">
                      <Link to={"/filelib"} target="_blank">
                        <Button variant="link">
                          <PlusCircledIcon className="mr-1" />{" "}
                          {t("build.createNewKnowledge")}
                        </Button>
                      </Link>
                      <Button variant="link" onClick={() => reload(1, '')}>
                        <ReloadIcon className="mr-1" /> {t("build.refresh")}
                      </Button>
                    </div>
                  )}
                </KnowledgeSelect>
              </div>
            </div>
          </AccordionContent>
        </AccordionItem>
      </Accordion>
      <h1 className="border-b bg-gray-50 indent-4 text-sm leading-8 text-muted-foreground">
        {t("build.abilities")}
      </h1>
      <Accordion
        type="multiple"
        className="w-full"
        onValueChange={(e) =>
          e.includes("skill") &&
          document.getElementById("skill-scroll").scrollTo({ top: 9999 })
        }
      >
        {/* 工具 */}
        <AccordionItem value="item-1">
          <AccordionTrigger>
            <div className="flex flex-1 items-center justify-between">
              <span>{t("build.tools")}</span>
              <ToolsSheet
                select={assistantState.tool_list}
                onSelect={(tool) =>
                  dispatchAssistant("setting", {
                    tool_list: [...assistantState.tool_list, tool],
                  })
                }
              >
                <PlusIcon
                  className="mr-2 text-primary hover:text-primary/80"
                  onClick={(e) => e.stopPropagation()}
                ></PlusIcon>
              </ToolsSheet>
            </div>
          </AccordionTrigger>
          <AccordionContent>
            <div className="px-4">
              {assistantState.tool_list.map((tool) => (
                <div
                  key={tool.id}
                  className="group mt-2 flex cursor-pointer items-center justify-between"
                >
                  <div className="flex items-center gap-2">
                    <TitleIconBg id={tool.id} className="h-7 w-7">
                      <ToolIcon />
                    </TitleIconBg>
                    <p className="text-sm">{tool.name}</p>
                  </div>
                  <MinusCircledIcon
                    className="hidden text-primary group-hover:block"
                    onClick={() =>
                      dispatchAssistant("setting", {
                        tool_list: assistantState.tool_list.filter(
                          (t) => t.id !== tool.id
                        ),
                      })
                    }
                  />
                </div>
              ))}
            </div>
          </AccordionContent>
        </AccordionItem>
        {/* 技能 */}
        <AccordionItem value="skill">
          <AccordionTrigger>
            <div className="flex flex-1 items-center justify-between">
              <span className="flex items-center gap-1">
                <span>{t("build.skill")}</span>
                <TooltipProvider delayDuration={200}>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <QuestionMarkCircledIcon />
                    </TooltipTrigger>
                    <TooltipContent>
                      <p>{t("build.skillDescription")}</p>
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </span>
              <SkillSheet
                select={assistantState.flow_list}
                onSelect={(flow) =>
                  dispatchAssistant("setting", {
                    flow_list: [...assistantState.flow_list, flow],
                  })
                }
              >
                <PlusIcon
                  className="mr-2 text-primary hover:text-primary/80"
                  onClick={(e) => e.stopPropagation()}
                ></PlusIcon>
              </SkillSheet>
            </div>
          </AccordionTrigger>
          <AccordionContent>
            <div className="px-4">
              {assistantState.flow_list.map((flow) => (
                <div
                  key={flow.id}
                  className="group mt-2 flex cursor-pointer items-center justify-between"
                >
                  <div className="flex items-center gap-2">
                    <TitleIconBg id={flow.id} className="h-7 w-7"></TitleIconBg>
                    <p className="text-sm">{flow.name}</p>
                  </div>
                  <MinusCircledIcon
                    className="hidden text-primary group-hover:block"
                    onClick={() =>
                      dispatchAssistant("setting", {
                        flow_list: assistantState.flow_list.filter(
                          (t) => t.id !== flow.id
                        ),
                      })
                    }
                  />
                </div>
              ))}
            </div>
          </AccordionContent>
        </AccordionItem>
      </Accordion>
    </div>
  );
}
