from rest_framework import status
from rest_framework.decorators import detail_route, list_route
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.status import HTTP_410_GONE
from rest_framework_mongoengine import viewsets

from enrollments.models import Course, Student
from enrollments.serializers import CourseSerializer, StudentSerializer


class CourseViewSet(viewsets.ModelViewSet):
    '''
    View, create, or update courses.
    '''
    lookup_field = 'id'

    serializer_class = CourseSerializer

    permission_classes = (AllowAny,)

    def get_queryset(self):
        queryset = Course.objects.all()
        minimal_points = self.request.query_params.get('minimal_points', None)
        if minimal_points is not None:
            queryset = queryset.filter(points__gte=minimal_points)
        return queryset

    def destroy(self, request, *args, **kwargs):
        course = self.get_object()
        students = course.get_enrolled_students(Student.objects.all())

        def de_enrol(student):
            for enrollment in filter(lambda enrollment: enrollment.course == course, student.enrollments):
                student.enrollments.remove(enrollment)
            student.save()

        map(de_enrol, students)

        self.perform_destroy(course)
        return Response(status=status.HTTP_204_NO_CONTENT)


class StudentViewSet(viewsets.ModelViewSet):
    '''
    View, create, or update students.

    parameters:
        - name: name
          in: query
          description: Partial student name.
          required: false
          type: string

    '''
    lookup_field = 'id'
    serializer_class = StudentSerializer

    permission_classes = (AllowAny,)

    def get_queryset(self):
        queryset = Student.objects.all()
        name = self.request.query_params.get('name', None)
        if name is not None:
            queryset = queryset.filter(name__contains=name)
        city = self.request.query_params.get('city', None)
        if city is not None:
            queryset = queryset.filter(city__contains=city)

        minimal_year = self.request.query_params.get('minimal_year', None)
        if minimal_year is not None:
            queryset = queryset.filter(year_of_birth__gte=minimal_year)

        return queryset

    def get_outstanding_students(self, minimum_score=1):
        def calc_score(student):
            sum = 0
            points = 0
            for enrollment in student.enrollments:
                sum += enrollment.grade * enrollment.course.points
                points += enrollment.course.points
            if points > 0:
                return student, sum / points
            else:
                return student, 0

        student_scores = map(calc_score, self.get_queryset())
        high_student_scores = filter(lambda student_scores: student_scores[1] >= minimum_score, student_scores)
        high_student_scores = sorted(high_student_scores, key=lambda x: x[1], reverse=True)
        just_high_students = map(lambda student_score: student_score[0], high_student_scores)
        return just_high_students

    @list_route(permission_classes=[AllowAny])
    def outstanding(self, request):
        '''
        Get list of outstanding students, whose weighted grade average is above or equal to 90.
        '''
        outstanding_students = self.get_outstanding_students(minimum_score=90)
        return Response(self.get_serializer(outstanding_students, many=True).data)

    @list_route(permission_classes=[AllowAny])
    def valedictorian(self, request):
        '''
        Get the student with the highest weighted grade average.

        410 GONE will be returned if there's no qualifying student
        '''
        outstanding_students = self.get_outstanding_students()
        if not outstanding_students:
            return Response({}, status=HTTP_410_GONE)
        valedict = outstanding_students[0]
        return Response(self.get_serializer(valedict).data)

    @list_route(methods=['post'], permission_classes=[AllowAny])
    def bulk_enrol(self, request, **kwargs):
        '''
        Bulk enroll all students, filtering applies.
        Pass course={course-id} in the query to point to a course.
        '''
        course_id = request.query_params.get('course')
        try:
            course = Course.objects.get(id=course_id)
        except Exception as e:
            return Response(data={'error': 'Invalid course_id %s' % course_id, 'details': e.message},
                            status=status.HTTP_400_BAD_REQUEST)

        def enrol_and_save(student):
            student.enrol(course)
            student.save()

        map(enrol_and_save, self.get_queryset())

        return Response(self.get_serializer(self.get_queryset(), many=True).data)

    @list_route(permission_classes=[AllowAny])
    def enrolled(self, request, **kwargs):
        '''
        Get all students enrolled to a specific course.

        Pass course-id as a query parameter `course`.
        '''
        course_id = request.query_params.get('course')
        try:
            course = Course.objects.get(id=course_id)
        except Exception as e:
            return Response(data={'error': 'Invalid course_id %s' % course_id, 'details': e.message},
                            status=status.HTTP_400_BAD_REQUEST)

        enrolled_students = course.get_enrolled_students(self.get_queryset())

        serializer = self.get_serializer(enrolled_students, many=True)
        return Response(serializer.data)

    @detail_route(methods=['post'], permission_classes=[AllowAny], url_path='enrol')
    def enrol(self, request, id=None):
        '''
        Enrol a student to a course. Course id should be passed via course query parameter
        '''
        student = self.get_object()

        course_id = request.data.get('course')
        try:
            course = Course.objects.get(id=course_id)
        except Exception as e:
            return Response(data={'error': 'Invalid course_id %s' % course_id, 'details': e.message},
                            status=status.HTTP_400_BAD_REQUEST)

        if course in student.enrolled_courses():
            return Response(data={'error': 'Student already enrolled to course %s' % course_id, 'details': ''},
                            status=status.HTTP_400_BAD_REQUEST)

        student.enrol(course)
        student.save()
        return Response(self.get_serializer(student).data)

    @detail_route(methods=['post'], permission_classes=[AllowAny], url_path='grade')
    def grade(self, request, id=None):
        '''
        Set the grade for a given student. Pass grade and course id via request body
        '''
        student = self.get_object()
        course_id = request.data.get('course')
        try:
            course = Course.objects.get(id=course_id)
        except Exception as e:
            return Response(data={'error': 'Invalid course_id %s' % course_id, 'details': e.message},
                            status=status.HTTP_400_BAD_REQUEST)

        if course not in student.enrolled_courses():
            return Response(data={'error': 'Student not enrolled to course %s' % course_id, 'details': ''},
                            status=status.HTTP_400_BAD_REQUEST)

        enrollment = filter(lambda enrollment: enrollment.course == course, student.enrollments)[0]
        enrollment.grade = request.data.get('grade')
        student.save()
        return Response(self.get_serializer(student).data)
