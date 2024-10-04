import streamlit as st
from openai import OpenAI
import os
import PyPDF2
import io
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph
from reportlab.lib.styles import getSampleStyleSheet
from datetime import datetime
import pandas as pd
import json
from typing import List, Dict

# Initialize OpenAI client
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# Initialize session states
if 'students' not in st.session_state:
    st.session_state.students = []
if 'quiz_history' not in st.session_state:
    st.session_state.quiz_history = []
if 'lesson_plan_history' not in st.session_state:
    st.session_state.lesson_plan_history = []

# Available subjects
SUBJECTS = [
    'Mathematics', 'Physics', 'Chemistry', 'Biology', 'English',
    'History', 'Geography', 'Computer Science', 'Art', 'Music'
]

def get_openai_api_key():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        api_key = st.text_input("Enter your OpenAI API key:", type="password")
        if not api_key:
            st.warning("Please enter a valid OpenAI API key to proceed.")
            st.stop()
    return api_key

def generate_lesson_plan(age, subject, topic):
    client = OpenAI(api_key=get_openai_api_key())
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are an experienced educator skilled in creating personalized lesson plans."},
            {"role": "user", "content": f"Create a detailed, age-appropriate lesson plan for a {age}-year-old learning about the topic '{topic}' within the subject of {subject}. Include learning objectives, activities, and assessment methods."}
        ],
        max_tokens=1000,
        n=1,
        temperature=0.7,
    )
    lesson_plan = response.choices[0].message.content.strip()
    return lesson_plan

def read_pdf(file):
    pdf_reader = PyPDF2.PdfReader(file)
    text = ""
    for page in pdf_reader.pages:
        text += page.extract_text()
    return text

def generate_quiz(content, num_questions):
    client = OpenAI(api_key=get_openai_api_key())
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are an expert at creating quizzes based on given content."},
            {"role": "user", "content": f"Create a quiz with {num_questions} questions based on the following content. Format the output as follows:\n\nQ1. [Question 1]\nA1. [Answer 1]\n\nQ2. [Question 2]\nA2. [Answer 2]\n\n... and so on:\n\n{content[:10000]}"}
        ],
        max_tokens=2000,
        n=1,
        temperature=0.7,
    )
    quiz = response.choices[0].message.content.strip()
    return quiz

def split_questions_answers(quiz):
    lines = quiz.split('\n')
    questions = []
    answers = []

    current_q = ""
    current_a = ""

    for line in lines:
        if line.startswith('Q'):
            if current_q:
                questions.append(current_q)
                answers.append(current_a)
            current_q = line
            current_a = ""
        elif line.startswith('A'):
            current_a = line

    if current_q:
        questions.append(current_q)
        answers.append(current_a)

    return '\n\n'.join(questions), '\n\n'.join(answers)

def create_pdf(content):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    flowables = []

    for line in content.split('\n'):
        p = Paragraph(line, styles['Normal'])
        flowables.append(p)

    doc.build(flowables)
    buffer.seek(0)

    return buffer

def parse_availability(availability_text):
    """Parse fuzzy availability text using OpenAI."""
    system_prompt = """
    Convert the given availability text into a JSON object with this structure:
    {
        "Monday": {"available": true/false, "start": "HH:MM", "end": "HH:MM"},
        "Tuesday": {"available": true/false, "start": "HH:MM", "end": "HH:MM"},
        "Wednesday": {"available": true/false, "start": "HH:MM", "end": "HH:MM"},
        "Thursday": {"available": true/false, "start": "HH:MM", "end": "HH:MM"},
        "Friday": {"available": true/false, "start": "HH:MM", "end": "HH:MM"},
        "Saturday": {"available": true/false, "start": "HH:MM", "end": "HH:MM"},
        "Sunday": {"available": true/false, "start": "HH:MM", "end": "HH:MM"}
    }
    For days not mentioned, set "available": false and times to "00:00".
    """

    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Parse this availability: {availability_text}"}
            ],
            temperature=0
        )

        availability = json.loads(response.choices[0].message.content)

        # Convert string times to datetime.time objects
        for day in availability:
            if availability[day]["available"]:
                start = datetime.strptime(availability[day]["start"], "%H:%M").time()
                end = datetime.strptime(availability[day]["end"], "%H:%M").time()
                availability[day]["start"] = start
                availability[day]["end"] = end
            else:
                availability[day]["start"] = datetime.time(0, 0)
                availability[day]["end"] = datetime.time(0, 0)

        return availability
    except Exception as e:
        st.error(f"Error parsing availability: {str(e)}")
        return None

def generate_timetable(students: List[Dict], teacher_availability: str):
    """Generate timetable using OpenAI."""
    system_prompt = """
    Create an optimal weekly timetable following these rules:
    1. Each subject has exactly 2 sessions per week
    2. Each session is 60 minutes long
    3. Sessions must be scheduled during both student and teacher availability
    4. No time conflicts between students
    5. Maximum 8 hours of teaching per day
    6. Include 15-minute breaks between sessions
    7. Try to spread subjects evenly across the week

    Return the timetable in this JSON format:
    {
        "sessions": [
            {
                "day": "Monday",
                "start_time": "14:00",
                "student_name": "student name",
                "subject": "subject name"
            }
        ]
    }
    """

    try:
        # Format student data
        students_data = []
        for student in students:
            student_info = {
                "name": student["name"],
                "subjects": student["subjects"],
                "availability": {
                    day: {
                        "available": times["available"],
                        "start": times["start"].strftime("%H:%M") if times["available"] else "00:00",
                        "end": times["end"].strftime("%H:%M") if times["available"] else "00:00"
                    }
                    for day, times in student["availability"].items()
                }
            }
            students_data.append(student_info)

        # Create context for AI
        context = {
            "students": students_data,
            "teacher_availability": teacher_availability,
            "constraints": {
                "sessions_per_subject": 2,
                "session_duration_minutes": 60,
                "break_duration_minutes": 15,
                "max_hours_per_day": 8
            }
        }

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(context)}
            ],
            temperature=0.5
        )

        return json.loads(response.choices[0].message.content)
    except Exception as e:
        st.error(f"Error generating timetable: {str(e)}")
        return None

def student_management_system():
    st.title("📚 Student Management System")

    # Create tabs
    tab1, tab2 = st.tabs(["🎓 Student Registration", "📅 Timetable Generator"])

    with tab1:
        registration_tab()

    with tab2:
        timetable_tab()

def registration_tab():
    st.header("Student Registration")

    # Registration Form
    with st.form("student_registration"):
        name = st.text_input("Student Name")
        age = st.number_input("Age", min_value=5, max_value=100, value=15)

        subjects = st.multiselect(
            "Select Subjects (maximum 3)",
            options=SUBJECTS,
            max_selections=3
        )

        availability_text = st.text_area(
            "Student Availability",
            help="Example: 'Monday 2pm-10pm, Wednesday mornings 9-11'",
            placeholder="Enter availability. Example: Available on Monday from 5pm to 7pm..."
        )

        submitted = st.form_submit_button("Register Student")

        if submitted:
            if not name or not subjects or not availability_text:
                st.error("Please fill in all required fields.")
            else:
                availability = parse_availability(availability_text)
                if availability:
                    student = {
                        "name": name,
                        "age": age,
                        "subjects": subjects,
                        "availability": availability
                    }
                    st.session_state.students.append(student)
                    st.success(f"Successfully registered {name}!")

    # Display registered students
    if st.session_state.students:
        st.header("Registered Students")

        for idx, student in enumerate(st.session_state.students):
            with st.expander(f"📝 {student['name']} (Age: {student['age']})"):
                st.write("**Subjects:**", ", ".join(student['subjects']))

                # Availability table
                st.write("**Weekly Availability:**")
                availability_data = []

                for day, times in student['availability'].items():
                    if times['available']:
                        status = "Available"
                        time_range = f"{times['start'].strftime('%I:%M %p')} - {times['end'].strftime('%I:%M %p')}"
                    else:
                        status = "Not Available"
                        time_range = "-"

                    availability_data.append({
                        "Day": day,
                        "Status": status,
                        "Time": time_range
                    })

                df = pd.DataFrame(availability_data)
                st.dataframe(
                    df,
                    hide_index=True,
                    column_config={
                        "Day": st.column_config.TextColumn("Day", width="medium"),
                        "Status": st.column_config.TextColumn("Status", width="medium"),
                        "Time": st.column_config.TextColumn("Time", width="large")
                    }
                )

                if st.button(f"Delete {student['name']}", key=f"delete_{idx}"):
                    st.session_state.students.pop(idx)
                    st.success("Student deleted successfully!")
                    st.rerun()
    else:
        st.info("No students registered yet.")

def timetable_tab():
    st.header("Timetable Generator")

    if not st.session_state.students:
        st.warning("No students registered. Please register students first.")
        return

    # Display student summary
    st.subheader("Registered Students Summary")
    for student in st.session_state.students:
        st.write(f"- {student['name']}: {', '.join(student['subjects'])}")

    # Teacher availability input
    st.subheader("Teacher Availability")
    teacher_availability = st.text_area(
        "Enter your availability",
        help="Example: 'Monday to Friday 9am-5pm, Saturday 10am-2pm'",
        placeholder="Enter your availability schedule..."
    )

    if st.button("Generate Timetable"):
        if not teacher_availability:
            st.error("Please enter your availability.")
            return

        with st.spinner("Generating optimal timetable..."):
            timetable = generate_timetable(st.session_state.students, teacher_availability)
            if timetable:
                st.success("Timetable generated successfully!")

                # Display timetable by day
                st.header("📅 Weekly Schedule")
                days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

                for day in days:
                    day_sessions = [s for s in timetable["sessions"] if s["day"] == day]
                    if day_sessions:
                        st.subheader(day)
                        df = pd.DataFrame(day_sessions)
                        df = df[["start_time", "student_name", "subject"]]
                        df.columns = ["Time", "Student", "Subject"]
                        st.dataframe(df, hide_index=True)

                # Create downloadable CSV
                df = pd.DataFrame(timetable["sessions"])
                csv = df.to_csv(index=False)
                st.download_button(
                    label="📥 Download Complete Timetable (CSV)",
                    data=csv,
                    file_name="weekly_timetable.csv",
                    mime="text/csv"
                )

                # Display schedule statistics
                st.header("📊 Schedule Statistics")
                sessions_df = pd.DataFrame(timetable["sessions"])

                col1, col2 = st.columns(2)

                with col1:
                    st.subheader("Sessions per Student")
                    student_sessions = sessions_df["student_name"].value_counts()
                    st.dataframe(
                        pd.DataFrame({
                            "Student": student_sessions.index,
                            "Total Sessions": student_sessions.values
                        })
                    )

                with col2:
                    st.subheader("Sessions per Day")
                    day_sessions = sessions_df["day"].value_counts()
                    st.dataframe(
                        pd.DataFrame({
                            "Day": day_sessions.index,
                            "Total Sessions": day_sessions.values
                        })
                    )

# Set up the page configuration
st.set_page_config(page_title="TutorCruncher", layout="wide")

# Navigation using sidebar
page = st.sidebar.selectbox("Select a Page", ["Home", "Student Management System", "Lesson Plan Generator", "Quiz Generator", "History"])

if page == "Home":
    st.title("🎓 TutorCruncher")
    st.header("Welcome to TutorCruncher!")
    st.write("""
    This application is designed to help educators create personalized lesson plans and quizzes effortlessly.
    With our intuitive interface, you can generate tailored educational materials based on age, subject, and topic.
    We've also added a Student Management System to help you organize your students and create timetables.
    """)

elif page == "Student Management System":
    student_management_system()

elif page == "Lesson Plan Generator":
    st.header("👩🏼‍🏫 Personalized Lesson Plan Generator")

    age = st.number_input("Enter the age:", min_value=1, max_value=100, value=10)
    subject = st.text_input("Enter the subject your student wants to learn:")
    topic = st.text_input("Enter the specific topic within the subject:")

    if st.button("Generate Lesson Plan"):
        if subject and topic:
            with st.spinner('Generating your personalized lesson plan...'):
                try:
                    lesson_plan = generate_lesson_plan(age, subject, topic)
                    st.subheader("Your Personalized Lesson Plan:")
                    st.write(lesson_plan)

                    # Save lesson plan to history
                    timestamped_lesson_plan_entry = {
                        'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        'lesson_plan': lesson_plan,
                        'subject': subject,
                        'topic': topic,
                        'age': age
                    }
                    st.session_state.lesson_plan_history.append(timestamped_lesson_plan_entry)

                except Exception as e:
                    st.error(f"An error occurred: {str(e)}")
        else:
            st.warning("Please enter both a subject and a topic before generating the lesson plan.")

elif page == "Quiz Generator":
    st.header("📝 Quiz Generator from PDF")

    uploaded_file = st.file_uploader("Upload a PDF file", type="pdf")
    num_questions = st.slider("Number of questions", min_value=5, max_value=10, value=5)

    if uploaded_file is not None:
        if st.button("Generate Quiz"):
            with st.spinner('Reading PDF and generating quiz...'):
                try:
                    pdf_content = read_pdf(uploaded_file)
                    quiz = generate_quiz(pdf_content, num_questions)

                    questions_only, answers_only = split_questions_answers(quiz)

                    st.subheader("Generated Quiz Questions:")
                    st.write(questions_only)

                    st.subheader("Generated Quiz Answers:")
                    st.write(answers_only)

                    questions_pdf = create_pdf(questions_only)
                    answers_pdf = create_pdf(answers_only)

                    col1, col2 = st.columns(2)

                    with col1:
                        st.download_button(
                            label="Download Questions Only (PDF)",
                            data=questions_pdf,
                            file_name="quiz_questions.pdf",
                            mime="application/pdf"
                        )

                    with col2:
                        st.download_button(
                            label="Download Answers Only (PDF)",
                            data=answers_pdf,
                            file_name="quiz_answers.pdf",
                            mime="application/pdf"
                        )

                    # Add quiz to history
                    timestamped_quiz_entry = {
                        'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        'questions': questions_only,
                        'answers': answers_only,
                        'file_name': uploaded_file.name
                    }
                    st.session_state.quiz_history.append(timestamped_quiz_entry)

                except Exception as e:
                    st.error(f"An error occurred: {str(e)}")
    else:
        st.warning("Please upload a PDF file to generate a quiz.")

elif page == "History":
    st.header("📅 Quiz History")

    if not st.session_state.quiz_history:
        st.write("No quizzes generated yet. Generate a quiz in the Quiz Generator tab to see it here.")
    else:
        for i, quiz in enumerate(reversed(st.session_state.quiz_history)):
            with st.expander(f"Quiz {len(st.session_state.quiz_history) - i}: {quiz['file_name']} - {quiz['timestamp']}"):
                st.write("Questions:")
                st.write(quiz['questions'])
                st.write("Answers:")
                st.write(quiz['answers'])

                questions_pdf = create_pdf(quiz['questions'])
                answers_pdf = create_pdf(quiz['answers'])

                col1, col2 = st.columns(2)

                with col1:
                    st.download_button(
                        label="Download Questions (PDF)",
                        data=questions_pdf,
                        file_name=f"quiz_questions_{i}.pdf",
                        mime="application/pdf"
                    )

                with col2:
                    st.download_button(
                        label="Download Answers (PDF)",
                        data=answers_pdf,
                        file_name=f"quiz_answers_{i}.pdf",
                        mime="application/pdf"
                    )

    st.header("📚 Lesson Plan History")

    if not st.session_state.lesson_plan_history:
        st.write("No lesson plans generated yet. Generate a lesson plan in the Lesson Plan Generator tab to see it here.")
    else:
        for i, lesson_plan in enumerate(reversed(st.session_state.lesson_plan_history)):
            with st.expander(f"Lesson Plan {len(st.session_state.lesson_plan_history) - i}: {lesson_plan['subject']} - {lesson_plan['topic']} (Age: {lesson_plan['age']}) - {lesson_plan['timestamp']}"):
                st.write(lesson_plan['lesson_plan'])

                lesson_plan_pdf = create_pdf(lesson_plan['lesson_plan'])
                st.download_button(
                    label="Download Lesson Plan (PDF)",
                    data=lesson_plan_pdf,
                    file_name=f"lesson_plan_{i}.pdf",
                    mime="application/pdf"
                )

if __name__ == "__main__":
    pass