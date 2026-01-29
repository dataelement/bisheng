import re
import unittest
from unittest import TestCase

from bisheng.workflow.nodes.report.text_classification import Patterns
from bisheng.workflow.nodes.report.text_classification import TextClassificationReport

sample_text = """
# Sample Report

## 二级标题

### 三级标题

#### 四级标题

##### 五级标题

###### 六级标题

####### 七级标题

This is a sample report with an image and a table.
![Sample Image](https://example.com/image.png)
https://example.com/data.xlsx
http://example.com/data.csv
http://example.com/image.jpg
http://example.com/image.png
http://example.com/image.bmp
http://example.com/image.gif
http://example.com/image.webp

/bisheng/tmp1.png?dadsaa=adas /bisheng/tmp2.png

你好吗？这是**重点**
你好？这也是__重点__
| Header 1 | Header 2 |
|----------|----------|
| Data 1   | Data **2**   |
"""


class TestDocxStringClassification(TestCase):
    def setUp(self):
        self.text_classification = TextClassificationReport("/tmp/bisheng")

    def test_patterns(self):
        for one in Patterns:
            print(f"\n\nPattern Name: {one.name}, Type: {one.resource_type}\n\n")
            match_text = []
            for match in re.finditer(one.pattern, sample_text, flags=one.flags):
                raw_text = match.group(0)
                match_text.append(raw_text)
            if not match_text:
                print(f"No matches found for pattern: {one.name}")
            else:
                print(f"Matches found for pattern: {match_text}")

    def test_text_classification(self):
        all_data = self.text_classification.get_all_classified_data(sample_text)
        print(all_data)


if __name__ == "__main__":
    unittest.main()
