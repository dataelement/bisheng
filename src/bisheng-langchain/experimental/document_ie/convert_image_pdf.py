import os
import glob
import fitz
import time
from tqdm import tqdm
from PIL import Image


def pic2pdf(img_dir, pdfFile):
    if os.path.exists(pdfFile):
        return
    doc = fitz.open()
    for img in sorted(glob.glob("{}/*".format(img_dir))):
        if os.path.isdir(img):
            continue
        imgdoc = fitz.open(img)
        pdfbytes = imgdoc.convert_to_pdf()
        imgpdf = fitz.open("pdf", pdfbytes)
        doc.insert_pdf(imgpdf)
    if os.path.exists(pdfFile):
        os.remove(pdfFile)
    doc.save(pdfFile)
    doc.close()


if __name__ == "__main__":
    img_dirs = ['保密条款/L1', '采购合同/原材料采购合同/W1', '采购合同/外协配套件采购合同/J18', '采购合同/外协件采购合同/JYT-1',
               '采购合同/生产采购一般条款/JYT-1', '采购合同/汽车服务备件采购协议/J7', '价格协议/J3', '价格协议/J4', '价格协议/J10',
               '供货合同/W26', '框架协议/产品开发协议/J5', '框架协议/物料采购框架协议/J6', '框架协议/销售协议/J44', '框架协议/主供货协议/J28',
               '买卖合同/J23', '买卖合同/J30', '项目定点合同/采购目标协议书/J22', '项目定点合同/采购目标协议书/J42', '项目定点合同/采购目标协议书/J44',
               '施工合同/W22', '施工合同/W23', '施工合同/W24', '销售合同/W25', '销售价格协议/W18', '最高额保证合同/W27', '最高额保证合同/W28',
               '最高额抵押合同/W29', '最高额抵押合同/W30', '最高额抵押合同/W31', '价格单/L-1', '价格单/L-2', '价格单/L-3']

    base_folder = '/Users/gulixin/Documents/数据项素/工作/项目支持/华泰合同/重大商务合同(汇总)'
    save_folder = '/Users/gulixin/Documents/数据项素/工作/项目支持/华泰合同/重大商务合同(汇总)_pdf'
    if not os.path.exists(save_folder):
        os.makedirs(save_folder)
    for img_dir in tqdm(img_dirs):
        img_dir_abs_path = os.path.join(base_folder, img_dir)
        save_abs_path = os.path.join(save_folder, '_'.join(img_dir.split('/')) + '.pdf')

        start_time = time.time()
        pic2pdf(img_dir_abs_path, save_abs_path)
        print('time:', time.time() - start_time)