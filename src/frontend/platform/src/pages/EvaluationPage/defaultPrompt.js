export default `Extract following from given question and ground truth

Question:What powers the sun and what is its primary function?
Answer: The sun is powered by nuclear fission, similar to nuclear reactors on Earth, and its primary function is to provide light to the solar system.
Ground truth: The sun is actually powered by nuclear fusion, not fission. In its core, hydrogen atoms fuse to form helium, releasing a tremendous amount of energy. This energy is what lights up the sun and provides heat and light, essential for life on Earth. The sun's light also plays a critical role in Earth's climate system and helps to drive the weather and ocean currents.
Extracted statements:
[
{{
  "statements that are present in both the answer and the ground truth": ["The sun's primary function is to provide light"],
  "statements present in the answer but not found in the ground truth": ["The sun is powered by nuclear fission", "similar to nuclear reactors on Earth"],
  "relevant statements found in the ground truth but omitted in the answer": ["The sun is powered by nuclear fusion, not fission", "In its core, hydrogen atoms fuse to form helium, releasing a tremendous amount of energy", "This energy provides heat and light, essential for life on Earth", "The sun's light plays a critical role in Earth's climate system", "The sun helps to drive the weather and ocean currents"]
}}
]

Question: What is the boiling point of water?
Answer: The boiling point of water is 100 degrees Celsius at sea level.
Ground truth: The boiling point of water is 100 degrees Celsius (212 degrees Fahrenheit) at sea level, but it can change with altitude.
Extracted statements:
[
  {{
    "statements that are present in both the answer and the ground truth": ["The boiling point of water is 100 degrees Celsius at sea level"],
    "statements present in the answer but not found in the ground truth": [],
    "relevant statements found in the ground truth but omitted in the answer": ["The boiling point can change with altitude", "The boiling point of water is 212 degrees Fahrenheit at sea level"]
  }}
]

Question: What was the company's R&D expense as a percentage of revenue in 2021?
Answer: According to the information provided, the company's R&D expense accounted for 15.86% of revenue in 2021.
Ground truth: According to the company's prospectus data, the company's R&D expense accounted for 15.86% of revenue in 2021.
Extracted statements:
[
  {{
    "statements that are present in both the answer and the ground truth": ["The company's R&D expense accounted for 15.86% of revenue in 2021"],
    "statements present in the answer but not found in the ground truth": [],
    "relevant statements found in the ground truth but omitted in the answer": []
  }}
]

Question: What was the EBITDA of Dameng in 2021?
Answer: Dameng's EBITDA in 2021 was 491,898,700 yuan.
Ground truth: According to Dameng Database's prospectus data, Dameng's EBITDA in 2021 was 491,898,500 yuan.
Extracted statements:
[
  {{
    "statements that are present in both the answer and the ground truth": [],
    "statements present in the answer but not found in the ground truth": ["Dameng's EBITDA in 2021 was 491,898,700 yuan"],
    "relevant statements found in the ground truth but omitted in the answer": ["According to Dameng Database's prospectus data, Dameng's EBITDA in 2021 was 491,898,500 yuan"]
  }}
]

Question: What was Dameng's accounts receivable turnover ratio in 2022?
Answer: Based on the information provided, Dameng's accounts receivable turnover ratio in 2022 is unknown.
Ground truth: Sorry, Dameng has not yet disclosed its 2022 annual report data.
Extracted statements:
[
  {{
    "statements that are present in both the answer and the ground truth": ["Dameng's 2022 accounts receivable turnover ratio is unknown"],
    "statements present in the answer but not found in the ground truth": [],
    "relevant statements found in the ground truth but omitted in the answer": [],
  }}
]


Question:{question}
Answer: {answer}
Ground truth: {ground_truth}
Extracted statements:"""`